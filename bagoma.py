#!/usr/bin/env python
# vi:ai:tabstop=8:shiftwidth=4:softtabstop=4:expandtab:fdm=indent

"""
BaGoMa - BAckup GOogle MAil - A Smart GMail Backup Script

See the README file for full details. Run the script with no arguments to see
the available options.
"""

__version__ = "1.40"
__author__ = "Gabriel Burca (gburca dash bagoma at ebixio dot com)"
__copyright__ = "Copyright (C) 2010-2012 Gabriel Burca. Code under GPL License."
__license__ = """
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""


import cPickle as pickle
import imaplib
import sys
import os.path
import shutil
import re
import pprint
import hashlib
import time
import getpass
import imap_utf7
import ConfigParser
import logging
from optparse import OptionParser
from email.parser import HeaderParser
from email.utils import getaddresses, parsedate_tz, mktime_tz
from copy import deepcopy
from xml.dom.minidom import Document
from types import *

# For debugging
try:
    import pdb
except ImportError:
    set_trace = lambda: 0
else:
    set_trace = pdb.set_trace


options = None

# Special Google folder FLAGS returned with XLIST
SpecialFolderFlags = frozenset([
    '\\Inbox'       , # Inbox
    '\\AllMail'     , # [Gmail]/All Mail
    '\\Trash'       , # [Gmail]/Trash
    '\\Spam'        , # [Gmail]/Spam
    '\\Drafts'      , # [Gmail]/Drafts
    '\\Sent'        , # [Gmail]/Sent Mail
    '\\Important'   , # [Gmail]/Important
    '\\Starred'     , # [GMail]/Starred
])

# Special Google folder FLAGS we should ignore (choose from set above)
IgnoredFolderFlags = frozenset(['\\Spam', '\\Trash'])

# Folders to ignore by name (some EMail clients create their own Trash, etc...)
IgnoredFolders = ['Spam', 'Trash']

# Tell imaplib that XLIST works the same way as LIST
imaplib.Commands['XLIST'] = imaplib.Commands['LIST']

msgIdMatch  = re.compile(r'\bMessage-Id\: (.+)', re.IGNORECASE + re.MULTILINE)
uIdMatch    = re.compile(r'\bUID (\d+)', re.IGNORECASE)
lstRspMatch = re.compile(r'\((?P<flags>.*?)\) "(?P<delimiter>.*)" (?P<name>.*)')
intDateMatch= re.compile(r'\bINTERNALDATE "([^"]+)"')
flagsMatch  = re.compile(r'\bFLAGS \(([^\)]*)\)')

emailMatch  = re.compile(r'([\w\-\.+]+@((\w[\w\-]+)\.)+[\w\-]+)')

DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

def serialize(filename, value):
    f = open(filename, 'w')
    pickle.dump(value, f)
    f.close()

def deserialize(filename):
    try:
        f = open(filename, 'r')
        value = pickle.load(f)
        f.close()
        return value
    except:
        return {}


def status(msg, log2logger=True):
    """Logs a status message (or object)"""
    if type(msg) == unicode:
        print msg.encode('utf-8'),
    elif type(msg) in [StringType, IntType, LongType, FloatType]:
        print msg,
        msg = str(msg)
    else:
        msg = pprint.pformat(msg).strip()
        print msg,

    if log2logger: logger.info(msg)
    sys.stdout.flush()

def progressCli(msg):
    status(msg)

def progressGui(msg):
    status(msg + "\n")

class ImapServer(imaplib.IMAP4_SSL):
    def __init__(self, serverAddr, serverPort, email, pwd):
        if pwd is None:
            pwd = getpass.getpass()

        logger.info('Connecting to %s ...', options.server)
        imaplib.IMAP4_SSL.__init__(self, serverAddr, serverPort)

        logger.info('Logging in as %s ...', email)
        self.login(email, pwd)

        # Discover special folders by looking at flags (names changes with country):
        self.AllMailFolder = '[Gmail]/All Mail'
        self.IgnoredFolders = list(IgnoredFolders)

        typ, data = self.xlist("", "*")
        for row in data:
            flags, delimiter, imap_folder = ImapServer.parseListResponse(row)
            flags = set(flags.split())
            if "\\Noselect" not in flags:
                if "\\AllMail" in flags and "\\Noselect" not in flags:
                    self.AllMailFolder = imap_folder
                elif IgnoredFolderFlags.intersection(flags):
                    self.IgnoredFolders.append(imap_folder)


    def xlist(self, directory, pattern):
        """
        XLIST is an IMAP extension by Google and Apple.

        Does an XLIST, and returns the results. See getFolders() for how to
        process the results.
        """
        name = 'XLIST'
        typ, data = self._simple_command(name, directory, pattern)
        return self._untagged_response(typ, data, name)


    def getFolders(self):
        """Retruns a list of selectable folders on this server"""
        typ, data = self.list(pattern='*')
        folders = []
        for row in data:
            flags, delimiter, imap_folder = ImapServer.parseListResponse(row)
            flags = flags.split()
            if "\\Noselect" not in flags:
                folders.append(imap_folder)
        return folders


    @staticmethod
    def parseListResponse(line):
        """Parses the server response to the client's LIST command"""
        flags, delimiter, mailbox_name = lstRspMatch.match(line).groups()
        mailbox_name = mailbox_name.strip('"')
        return (flags, delimiter, mailbox_name)


    def upload(self, backupDir, msg, destFolder):
        """
        Finds the file containing the msg, and uploads it to the destFolder on the server.

        Returns the new UID assigned to the uploaded message, or None if it fails.
        """
        sha = msg['sha1']
        fullPath = os.path.join(backupDir, sha[0:2], sha)
        if not os.path.isfile(fullPath):
            logger.warn("Missing %s - can not upload %s" % (sha, fullPath))
            return None
        f = open(fullPath, "rb")
        flags = msg['flags']
        date = imaplib.Internaldate2tuple("INTERNALDATE \"" + msg['internaldate'] + "\"")
        result, data = self.append(destFolder, flags, date, f.read())
        f.close()

        # full data is: ('OK', ['[APPENDUID 1 11920] (Success)'])
        # data[0] format is: [APPENDUID UIDVALIDITY UID]
        match = re.search(r'APPENDUID (\d+) (\d+)', data[0])
        if result == 'OK' and match:
            msg['uid'] = match.group(2)
            return msg['uid']
        else:
            logger.warn("Unable to upload message %s to %s", fullPath, destFolder)
            return None


    def saveMsg(self, uid, shaHex, backupDir, folderName=None):
        """
        Saves a mail message locally. If backupDir does not exist, nothing is saved.

        @param uid The UID of the message to save
        @param shaHex The sha/file to save it to
        @param backupDir The directory to save it to
        @param folderName Optional name of the IMAP folder to retrieve the
            message from. If the folderName argument is not used, the folder to
            save from should be selected before calling this method.
        """

        if backupDir is None or not os.path.exists(backupDir):
            return False

        dir = os.path.join(backupDir, shaHex[0:2])
        if not os.path.exists(dir):
            os.makedirs(dir)

        fullPath = os.path.join(dir, shaHex)

        if folderName is not None:
            result, data = self.select(folderName, readonly=True)
            if result != 'OK':
                logger.error("Failed to select folder: " + folderName)
                return False

        if not os.path.exists(fullPath):
            # "with" not available until 2.6
            with open(fullPath, "wb") as msgFile:
                result, msgBody = self.uid('FETCH', uid, "RFC822")
                if result == 'OK':
                    msgFile.write(msgBody[0][1])
                    return True
                else:
                    logger.error("Failed to retrieve UID %d from server" % (uid))
        else:
            # This could be because the previous backup did not finish
            # (message was D/L'ed but folder indexing did not complete, so we
            # think it's a new message and are trying to D/L it again), OR it's
            # a true SHA1 duplicate.
            logger.warn("File %s already exists." % (shaHex))

        return False


    def saveAllMsgs(self, backupDir, oldMsgs, oldFlds):
        """
        Saves all new messages to the backupDir.

        @param backupDir The directory to save the messages in
        @param oldMsgs A dictionary of old messages that have been previously
            saved. If there are none, this should be an empty dict.
        @param oldFlds A dictionary of old folders that have been previously
            saved. If there are none, this should be an empty dict.
        """

        messages = {}

        folderName = self.AllMailFolder
        logger.info("Downloading messages from %s" % folderName)
        folder = EmailFolder(self, folderName)
        if not folder.OK:
            # TODO: Error handling
            logger.error("Unable to select folder: %s" % folderName)
            return messages

        if oldFlds.has_key(folderName) and oldFlds[folderName].sameUidVal(folder):
            # Lucky for us. UIDVALIDITY has not changed.
            msgUIDs = folder.carryOver(oldFlds[folderName], messages, oldMsgs, appendFolder=False)
        else:
            msgUIDs = folder.UIDs

        msgCnt = len(msgUIDs)
        status("Retained %5d message(s). Need to D/L %5d new message(s).\n" % (len(messages), msgCnt))
        saved = i = 0
        try:
            for uid in msgUIDs:
                i += 1
                msg = EmailMsg(self, uid)
                if not msg.OK:
                    logger.error("Could not retrieve UID %d from folder %s", uid, folderName)
                    # TODO: Error handling
                    continue

                msg['folder'] = [ folderName ]
                sha1 = msg['sha1']
                if messages.has_key(sha1):
                    old = messages[sha1]
                    dupSha1 = "__%s.%s" % (sha1, uid)
                    self.saveMsg(uid, dupSha1, backupDir)
                    logger.warn("Duplicate SHA1 found. UID: %s & %s. Saved to SHA1: %s" % (old['uid'], uid, dupSha1))
                    logger.debug("InternalDate: %s -- %s" % (old['internaldate'], msg['internaldate']))
                else:
                    if not oldMsgs.has_key(sha1):
                        self.saveMsg(uid, sha1, backupDir)
                        saved += 1
                    messages[sha1] = msg
                    folder.msgs[uid] = sha1

                progress('\r%.0f%% %d/%d ' % (i * 100.0 /msgCnt, i, msgCnt))
        except:
            status("\n", False)
            logger.debug("Saved %d/%d messages (%d candidates)" % (saved, msgCnt, i))
            logger.exception("Could not save all messages")

        #if len(messages) < 20:
        #    logger.debug(pprint.pformat(messages))
        status("\nSaved %s new message(s)\n" % (saved))
        return (messages, folder)


    def indexAllFolders(self, messages, oldFlds, allMailFld):
        """
        After doing saveAllMsgs(), this function finds all folders/tags with which a
        message is tagged.
        """
        folderInfo = {allMailFld.name:allMailFld}
        ignoreFolders = [self.AllMailFolder] + self.IgnoredFolders

        try:
            for folderName in [f for f in self.getFolders() if f not in ignoreFolders]:
                try:
                    folder = self.indexOneFolder(messages, oldFlds.get(folderName, None), folderName)
                except:
                    logger.exception("Could not proerly index folder: %s." % (folderName))
                    folder = None

                if folder is not None:
                    folderInfo[folderName] = folder
                else:
                    # Keep old folder data, otherwise we'll have to fully re-index next time
                    if oldFlds.has_key(folderName):
                        folderInfo[folderName] = oldFlds[folderName]
                    continue
        except:
            logger.exception("Could not index all folders.")
            # Old folder info is better than no info at all.
            folderInfo = oldFlds

        return (folderInfo, messages)


    def indexOneFolder(self, messages, oldFld, folderName):
        """
        Creates an EmailFolder object and populates its EmailFolder.msgs
        dictionary that maps UID => SHA1, either by copying the UID/SHA1 from
        oldFld (for old messages that were previously backed up), or by
        retrieving the message headers from the server by UID and computing the
        SHA1.

        Returns the created EmailFolder

        @param messages     Could be None.
        @param oldFld       If None, the new folder is fully indexed, otherwise
                            reuse the oldFld data to initialize the new folder.
        @param folderName   Name of the folder to index - mandatory
        """
        folder = EmailFolder(self, folderName)
        if folder.OK:
            status("Indexing: %s\n" % imap_utf7.decode(folderName))
        else:
            logger.error("Unable to select folder: %s" % folderName)
            return None

        if folder.sameUidVal(oldFld):
            msgUIDs = folder.carryOver(oldFld, messages, None)
        else:
            msgUIDs = folder.UIDs

        msgCnt = len(msgUIDs)
        status("Retained %5d message(s). Need to transfer %5d message(s).\n" % (len(folder.msgs), msgCnt))
        i = 0
        try:
            for uid in msgUIDs:
                i += 1
                msg = EmailMsg(self, uid)
                if not msg.OK:
                    logger.error("Could not retrieve UID %d from folder %s", uid, folderName)
                    # TODO: Error handling
                    continue

                folder.msgs[uid] = msg['sha1']
                if messages is not None:
                    sha1 = msg['sha1']
                    if messages.has_key(sha1) and folderName not in messages[sha1]['folder']:
                        messages[sha1]['folder'].append(folderName)
                    else:
                        # Assumes saveAllMsgs was called first, and messages
                        # contains a full list of all current SHA1's
                        logger.warn("New message arrived in %s while indexing %d/%d ?" % (folderName, i, msgCnt))

                progress('\r%.0f%% %d/%d ' % (i * 100.0 / msgCnt, i, msgCnt))
        except:
            status("\n", False)
            logger.debug("Indexed %d/%d" % (i, msgCnt))
            logger.exception("Could not fully index folder %s" % folderName)

        status("\n", False)
        return folder


class EmailFolder(dict):
    """
    When a folder object is created, it retrieves from the server:
        1. The folder's IMAP XLIST data (see parseSelectRsp)
        2. The folder's type (see SpecialFolderFlags)
        3. The UIDs of all messages in the folder

    Only the first 2 items are saved when the folder info is serialized to disk
    """
    def __init__(self, server, folder):
        self.OK = False
        self.name = folder

        # Key = UID, value = SHA1. See also getSha2Uid().
        self.msgs = {}

        # The UIDs in this folder, as reported by the server.
        # After a folder is indexed, this should be == self.msgs.keys()
        # This is maintained separate from self.msgs because when a folder
        # object is created by this __init__, all we have is UIDs.
        self.UIDs = []

        result, data = server.xlist("", folder)
        if result == 'OK':
            flags, delimiter, imap_folder = ImapServer.parseListResponse(data[0])
            self.update( {'Type' : frozenset(flags.split()).intersection(SpecialFolderFlags)} )
        else:
            self.update( {'Type' : frozenset()} )


        result, data = server.select(folder, readonly=True)
        if result == 'OK':
            self.update( EmailFolder.parseSelectRsp(server) )

            # result, data = server.uid('SEARCH', 'ALL')
            # For large folders, a "UID SEARCH ALL" could produce a very large response,
            # so we'll break it down into blocks of listSz

            listSz = 250
            lastMsg = self['EXISTS']
            if lastMsg > 5000:
                status("Retrieving %d message UIDs from %s. This might take a while.\n" % (lastMsg, self.name))

            if lastMsg == 0:
                # Empty folder
                self.OK = True
            else:
                for minMax in [(s, s + listSz - 1) for s in range(1, lastMsg + 1, listSz)]:
                    result, data = server.uid('SEARCH', '%d:%d' % minMax)
                    if result == 'OK':
                        self.UIDs.extend( data[0].split() )
                        self.OK = True
                    else:
                        self.OK = False
                        logger.warn("Could not retrieve all UIDs from: " + self.name)
                        break
        else:
            logger.warn("Could not select folder: " + self.name)


    @staticmethod
    def parseSelectRsp(server):
        FLAGS = imaplib.ParseFlags( server.response('FLAGS')[1][0] )
        UIDVALIDITY = int(server.response('UIDVALIDITY')[1][0])
        RECENT = int(server.response('RECENT')[1][0])
        EXISTS = int(server.response('EXISTS')[1][0])
        UIDNEXT = int(server.response('UIDNEXT')[1][0])
        result = {'FLAGS':FLAGS, 'UIDVALIDITY':UIDVALIDITY, 'RECENT':RECENT,
                'EXISTS':EXISTS, 'UIDNEXT':UIDNEXT}
        logger.debug(pprint.pformat(result))
        return result



    def sameUidVal(self, otherFld):
        if otherFld is not None:
            return self['UIDVALIDITY'] == otherFld['UIDVALIDITY']
        else:
            return False

    def getSha2Uid(self):
        sha2Uid = {}
        for uid, sha in self.msgs.items():
            sha2Uid[sha] = uid
        return sha2Uid


    def uidDiffIntersect(self, otherFld):
        """
            Computes the difference and intersection of the UIDs in this folder
            and the UIDs in the otherFld.

            When otherFld is the old folder, the diff contains new UIDs that
            were added since the last backup, and intersection contains UIDs
            that haven't changed.
        """
        if self.sameUidVal(otherFld):
            thisUid = set(self.UIDs)
            thatUid = set(otherFld.UIDs)

            # These are the new msgUIDs that were added since the last backup
            diff = list(thisUid.difference(thatUid))

            # These are the messages that haven't changed
            intersection = list(thisUid.intersection(thatUid))
            return (diff, intersection)
        else:
            return (None, None)

    def carryOver(self, oldFld, messages, oldMsgs, appendFolder = True):
        """
        @param oldFld The old folder (from the previous backup).
        @param messages The new messages
        @param oldMsgs The old messages (from the previous backup)
        @param appendFolder Should be false if we want to replace the old folder
        list.

        When indexing a folder, we leave the messages[sha] unchanged, and only
        append the new folder name to the list of folders the message is part
        of. When saving messages (saveAllMsgs) we carry over the message objects
        from oldMsgs to messages.
        """
        (msgUIDs, oldUIDs) = self.uidDiffIntersect(oldFld)

        # Retain the messages that haven't changed
        for uid in oldUIDs:
            if not oldFld.msgs.has_key(uid):
                # Happens if not all the messages were D/Led initially
                msgUIDs.append(uid)
                continue

            sha = oldFld.msgs[uid]

            if oldMsgs is not None:
                messages[sha] = oldMsgs[sha]

            if messages is not None:
                if appendFolder:
                    messages[sha]['folder'].append(self.name)
                else:
                    messages[sha]['folder'] = [ self.name ]

            self.msgs[uid] = oldFld.msgs[uid]

        return msgUIDs


class EmailMsg(dict):
    def __init__(self, server, uid):
        """The folder must be selected on the server before this function is called"""
        self.OK = False

        result, data = server.uid('FETCH', uid, '(UID FLAGS INTERNALDATE BODY[HEADER.FIELDS (FROM TO CC DATE SUBJECT X-GMAIL-RECEIVED MESSAGE-ID)])')
        # data == [("uid internaldate", "headers"), ')']
        if result == 'OK':
            try:
                # The UID changes based on the selected folder, but when serializing
                # we always serialize the UID for AllMailFolder
                self['uid'] = uIdMatch.search(data[0][0]).group(1)
                self['flags'] = flagsMatch.search(data[0][0]).group(1)
                self['internaldate'] = intDateMatch.search(data[0][0]).group(1)

                parser = HeaderParser()
                msg = parser.parsestr(data[0][1], headersonly=True)
                self['sha1'] = EmailMsg.computeSha1(self['internaldate'], msg)

                # The list of folders in which this message appears
                self['folder'] = []

                self.OK = True
            except:
                logger.exception("Error retrieving message")
                self.OK = False


    @staticmethod
    def computeSha1(internaldate, m):
        """
        Gets the SHA1 of the message.

        We don't use UID and UIDVALIDITY because when the UIDVALIDITY changes it
        obsoletes our whole message cache and we would need to re-download all
        the messages again. The IMAP standard is completely broken in this
        respect. What's the use of a unique ID, if the server can render it
        invalid at any time by changing the UIDVALIDITY?
        """

        hdrList = ['from', 'to', 'cc', 'date', 'subject', 'x-gmail-received', 'message-id']
        # We do the join/split business to normalize whitespace
        shaLst = [' '.join(m.get(hdr, "").split()) for hdr in hdrList]
        shaLst.insert(0, internaldate)

        goodHdrs = len([hdr for hdr in shaLst if len(hdr)])
        if goodHdrs < 4:
            # Expect at least internaldate, message-id, date, and from
            if goodHdrs <= 1:
                # Only internaldate?
                logger.error("No headers to compute SHA1 from. InternalDate = %s" % internaldate)
            else:
                logger.warn("Too few headers (%d/%d) to compute reliable SHA1" % (goodHdrs, len(hdrList) + 1))

        return hashlib.sha1("\n".join(shaLst)).hexdigest()


    @staticmethod
    def move(shaHexFrom, shaHexTo, backupDir):
        srcPath = os.path.join(backupDir, shaHexFrom[0:2], shaHexFrom)
        dstPath = os.path.join(backupDir, shaHexTo[0:2], shaHexTo)

        # Creates directories as needed
        os.renames(srcPath, dstPath)


class dict2xml(object):
    """
    Based on http://code.activestate.com/recipes/577739-dict2xml/
    """
    doc     = Document()

    def __init__(self, structure):
        """
        Usage:
            myDict = {......}
            xml = dict2xml( {'MyRoot': myDict} )

        @param structure Must be a dictionary, with a single key (the name of
        the root/top element)
        """
        if len(structure) == 1:
            rootName    = str(structure.keys()[0])
            self.root   = self.doc.createElement(rootName)

            self.doc.appendChild(self.root)
            self.build(self.root, structure[rootName])

    def build(self, father, structure):
        if type(structure) == dict:
            for k in sorted(structure.keys()):
                tag = self.doc.createElement(str(k))
                father.appendChild(tag)
                self.build(tag, structure[k])

        elif type(structure) == list:
            grandFather = father.parentNode
            tagName     = father.tagName
            grandFather.removeChild(father)
            for l in structure:
                tag = self.doc.createElement(tagName)
                self.build(tag, l)
                grandFather.appendChild(tag)

        else:
            data    = str(structure)
            tag     = self.doc.createTextNode(data)
            father.appendChild(tag)

    def display(self):
        print self.doc.toprettyxml(indent="  ")


class Stats(object):
    """
    Computes some basic email statistics
    """

    @staticmethod
    def extractStats(backupDir, msgIndexFile, fldIndexFile):
        """
        TODO:
            Messages received per day
            Messages sent per day
        """
        msgIndex = deserialize(msgIndexFile)
        fldIndex = deserialize(fldIndexFile)

        timeStats = {'Yrs':{}, 'DOW':{}, 'Hrs':{}}
        stats = {'CountTotalMsgs':0, 'CountListMsgs':0,
                 'CountSentMsgs':0, 'CountRcvdMsgs':0,
                 'TimeAll':deepcopy(timeStats),
                 'TimeSent':deepcopy(timeStats),
                 'TimeRcvd':deepcopy(timeStats)}
        hFrom = {}
        hTo = {}

        SentFolder = [f[0] for f in fldIndex.items() if '\\Sent' in f[1]['Type']][0]
        logger.debug("SentFolder=" + SentFolder)
        idx = 0
        status("Computing stats for %d message(s).\n" % (len(msgIndex)))

        for sha1 in msgIndex.keys():
            idx += 1
            fp = open(os.path.join(backupDir, sha1[0:2], sha1), 'r')

            firstLine = fp.readline()
            if firstLine.startswith('>From - '):
                # Broken headers that will trip up HeaderParser
                pass
            else:
                fp.seek(0)

            parser = HeaderParser()
            pMsg = parser.parse(fp, headersonly=True)
            fp.close()

            stats['CountTotalMsgs'] = stats['CountTotalMsgs'] + 1
            if pMsg.get('list-id', ""):
                stats['CountListMsgs'] = stats['CountListMsgs'] + 1
                continue

            date = parsedate_tz(pMsg.get('date', ""))
            if date != None:
                date = time.localtime( mktime_tz(date) )
            Stats.saveDateStats(stats['TimeAll'], date)

            #set_trace()
            if SentFolder in msgIndex[sha1]['folder']:
                stats['CountSentMsgs'] = stats['CountSentMsgs'] + 1
                try:
                    receivers = pMsg.get_all('to', []) + pMsg.get_all('cc', [])
                    for toEmail in [m[1].lower() for m in getaddresses(receivers) if len(m[1]) > 0]:
                        hTo[toEmail] = hTo.setdefault(toEmail, 0) + 1
                    Stats.saveDateStats(stats['TimeSent'], date)
                except:
                    logger.exception("Exception parsing recipient data")
            else:
                stats['CountRcvdMsgs'] = stats['CountRcvdMsgs'] + 1
                try:
                    for fromEmail in [m[1].lower() for m in getaddresses(pMsg.get_all('from', []))]:
                        hFrom[fromEmail] = hFrom.setdefault(fromEmail, 0) + 1
                    Stats.saveDateStats(stats['TimeRcvd'], date)
                except:
                    logger.exception("Exception parsing sender data")

            progress('\r%.0f%% %d/%d ' % (idx * 100.0 / len(msgIndex), idx, len(msgIndex)))


        xml = dict2xml({'Stats': stats})

        senders = xml.doc.createElement("Senders")
        xml.root.appendChild(senders)
        for email, count in sorted(hFrom.items(), key = lambda x: x[1], reverse=True):
            sender = xml.doc.createElement("Sender")
            sender.setAttribute("Email", email)
            sender.setAttribute("Count", str(count))
            senders.appendChild(sender)

        rcvrs = xml.doc.createElement("Receivers")
        xml.root.appendChild(rcvrs)
        for email, count in sorted(hTo.items(), key = lambda x: x[1], reverse=True):
            rcvr = xml.doc.createElement("Receiver")
            rcvr.setAttribute("Email", email)
            rcvr.setAttribute("Count", str(count))
            rcvrs.appendChild(rcvr)

        output = open("stats-{0}.xml".format(options.email), 'w')
        try:
            xml.doc.writexml(output, encoding='utf-8', indent='  ', addindent='  ', newl="\n")
        finally:
            output.close()


    @staticmethod
    def saveDateStats(stats, date):
        if date is None:
            return

        key = "Yr_%04d" % date.tm_year
        stats['Yrs'][key] = stats['Yrs'].setdefault(key, 0) + 1

        key = "Hr_%02d" % date.tm_hour
        stats['Hrs'][key] = stats['Hrs'].setdefault(key, 0) + 1

        key = "DOW_%d_%s" % (date.tm_wday, DOW[date.tm_wday])
        stats['DOW'][key] = stats['DOW'].setdefault(key, 0) + 1


def rotateFile(fName, levels, move=False):
    """Recursively copies (or moves) fName.1 to fName.2, fName to fName.1,
    etc... retaining files up to fName.n where n == levels"""
    if not os.path.exists(fName): return True

    name, num = re.search(r'(.+?)(?:\.(\d+))?$', fName).groups()
    if num is None:
        num = 1
    else:
        num = int(num) + 1

    target = "%s.%d" % (name, num)
    if levels > 1:
        if not rotateFile(target, levels - 1):
            return False

    try:
        if move:
            if os.path.exists(target):
                os.remove(target)
            os.rename(fName, target)
        else:
            shutil.copyfile(fName, target)
    except:
        logger.exception("Failed to rotate file")
        return False

    return True


def backup(server, backupDir, msgIndexFile, fldIndexFile):
    """
    Backs up the current state of the server. All messages are saved in
    backupDir, and metadata goes in the msgIndexFile and fldIndexFile.
    """

    # If backupDir does not exist, nothing is saved, so create it first.
    if not os.path.exists(backupDir):
        os.makedirs(backupDir)

    oldMsgs = deserialize(msgIndexFile)
    oldFlds = deserialize(fldIndexFile)
    rotateFile(msgIndexFile, 5)
    rotateFile(fldIndexFile, 5)

    messages, allMailFld = server.saveAllMsgs(backupDir, oldMsgs, oldFlds)
    if len(messages) >= 0:
        # Save msgIndex first, in case we run into problems later
        if len(msgIndexFile) > 0: serialize(msgIndexFile, messages)

        newFlds, messages = server.indexAllFolders(messages, oldFlds, allMailFld)

        if len(msgIndexFile) > 0: serialize(msgIndexFile, messages)
        if len(fldIndexFile) > 0: serialize(fldIndexFile, newFlds)

        #if len(messages) < 20:
        #    logger.debug(pprint.pformat(messages))
    else:
        logger.info("Not enough messages to back up")


def restore(server, backupDir, msgIndexFile, fldIndexFile):
    """
    Restores messages from the local backup. For messages that are already on
    the server, it restores the labels that were attached to the message when
    the backup was made.
    """
    if not os.path.exists(backupDir) or not os.path.exists(msgIndexFile) or not os.path.exists(fldIndexFile):
        return False

    oldMsgs = deserialize(msgIndexFile)
    oldFlds = deserialize(fldIndexFile)

    if not restoreAllMailFld(server, backupDir, oldMsgs, oldFlds[server.AllMailFolder]):
        return False

    currFolderNames = server.getFolders()
    oldNames = oldFlds.keys()
    oldNames.remove(server.AllMailFolder)
    for fn in server.IgnoredFolders:
        if fn in oldNames:
            oldNames.remove(fn)

    # Create missing folders (if any)
    for folderName in oldNames:
        if folderName not in currFolderNames:
            server.create(folderName)
            status("Created %s\n" % folderName)
            currFolderNames.append(folderName)

    # COPY messages from AllMail to other folders
    for folderName in oldNames:
        folder = EmailFolder(server, folderName)
        if not folder.OK:
            logger.error("Could not read and restore folder %s", folderName)
            continue

        oldFld = oldFlds[folderName]
        oldUid = set(oldFld.msgs.keys())

        # Figure out the list of missing SHA1's
        if oldFld.sameUidVal(folder):
            # Great. No need to re-index this folder.
            logger.debug("Restoring %s by UID", folderName)
            newUid = set(folder.UIDs)
            msgUIDs = list(oldUid.difference(newUid))
            missingSha1 = [oldFld.msgs[uid] for uid in msgUIDs]
        else:
            # UIDVALIDITY changed. Need to re-index.
            logger.debug("Restoring %s by SHA1", folderName)
            folder = server.indexOneFolder(None, oldFld, folderName)
            oldSha1 = set(oldFld.msgs.values())
            newSha1 = set(folder.msgs.values())
            missingSha1 = list(oldSha1.difference(newSha1))
            if len(missingSha1) == 0:
                # All local messages are already on the server, but UIDVALIDITY
                # differs. Update the local UIDs and UIDVALIDITY.
                updateLocalUIDs(oldFld, folder)

        server.select(server.AllMailFolder)
        copied = 0

        for sha1 in missingSha1:
            # This assumes msg['uid'] has been updated to the current UID in AllMail
            allMailUid = oldMsgs[sha1]['uid']
            # Not copying all msgs with a single COPY command (COPY 1 5 8 Destination)
            # b/c we lose fine grained error logging.
            result, data = server.uid("COPY", allMailUid, folderName)
            if result != 'OK':
                logger.error("Failed to copy %s (UID: %s) to %s" % (sha1, allMailUid, folderName))
            else:
                copied += 1

        if copied > 0:
            # Need to figure out the new UID of the messages that were copied.
            # This is more expensive than it needs to be. Would be nice if the IMAP
            # COPY command returned the new UID, like the IMAP APPEND command does.
            if copied == len(missingSha1):
                # All messages copied/restored successfully. We can safely update all
                # local UIDs.
                folder = server.indexOneFolder(None, oldFld, folderName)
                updateLocalUIDs(oldFld, folder)
            elif oldFld.sameUidVal(folder):
                # We have a partial copy. We can only update things for the case:
                #   old['UIDVALIDITY'] == new['UIDVALIDITY']
                # For the other case, we will have to continue restoring by SHA1
                # until all the messages have been restore, and then we'll call
                # updateLocalUIDs()
                folder = server.indexOneFolder(None, oldFld, folderName)
                sha2newUid = folder.getSha2Uid()
                for uid in oldUid:
                    sha1 = oldFld.msgs[uid]
                    if uid != sha2newUid[sha1]:
                        del( oldFld.msgs[uid] )
                        oldFld.msgs[ sha2newUid[sha1] ] = sha1
                oldFld.UIDs = list(oldFld.msgs.keys())

        status("Copied %d/%d messages from %s to %s\n" % (copied, len(missingSha1), server.AllMailFolder, folderName))

    serialize(fldIndexFile, oldFlds)
    serialize(msgIndexFile, oldMsgs)


def updateLocalUIDs(oldFld, newFld):
    """
        Precondition: newFld must contain a superset of the messages in oldFld.
    """
    sha2newUid = newFld.getSha2Uid()

    # Key = UID, value = SHA1
    oldSha1 = list(oldFld.msgs.values())
    oldFld.msgs.clear()
    for sha in oldSha1:
        oldFld.msgs[ sha2newUid[sha] ] = sha

    oldFld['UIDVALIDITY'] = newFld['UIDVALIDITY']
    oldFld.UIDs = list(oldFld.msgs.keys())


def restoreAllMailFld(server, backupDir, oldMsgs, oldFld):
    folder = EmailFolder(server, server.AllMailFolder)
    if not folder.OK:
        logger.warn("Unable to restore mail to %s", server.AllMailFolder)
        return False

    uploaded = 0
    if oldFld.sameUidVal(folder):
        oldUid = set(oldFld.msgs.keys())
        newUid = set(folder.UIDs)

        # Missing messages
        msgUIDs = list(oldUid.difference(newUid))

        for uid in msgUIDs:
            sha1 = oldFld.msgs[uid]
            newUid = server.upload(backupDir, oldMsgs[sha1], server.AllMailFolder)
            if newUid is not None:
                del( oldFld.msgs[uid] )
                oldFld.msgs[newUid] = sha1
                uploaded += 1
            else:
                # TODO: Error handling
                logger.error("Failed to upload SHA1 %s to AllMail folder" % sha1)
    else:
        folder = server.indexOneFolder(None, oldFld, server.AllMailFolder)
        oldSha1 = set(oldFld.msgs.values())
        newSha1 = set(folder.msgs.values())
        missingSha1 = list(oldSha1.difference(newSha1))

        sha2oldUid = {}
        for key, val in oldFld.msgs.items():
            sha2oldUid[val] = key

        for sha1 in missingSha1:
            newUid = server.upload(backupDir, oldMsgs[sha1], server.AllMailFolder)
            if newUid is not None:
                del( oldFld.msgs[ sha2oldUid[sha1] ] )
                oldFld.msgs[newUid] = sha1
                uploaded += 1
            else:
                # TODO: Error handling
                logger.error("Failed to upload SHA1 %s to AllMail folder" % sha1)

        oldFld.UIDs = list(oldFld.msgs.keys())
        oldFld['UIDVALIDITY'] = folder['UIDVALIDITY']
        # TODO: Copy other fields?

    status("Uploaded %d messages to %s\n" % (uploaded, server.AllMailFolder))
    return True


def purgeCallBack(arg, dirname, fnames):
    msgIndex = arg
    progress("\r%s" % dirname)
    for fname in [f for f in fnames if not re.search('pickle(\.\d+)?$', f)]:
        if not msgIndex.has_key(fname) and os.path.isfile(fname):
            status("Deleting stale file %s" % fname)
            if options.dryRun: continue
            os.remove(os.path.join(dirname, fname))


def reindexCallBack(arg, dirname, fnames):
    """
        Verifies that all files on disk are saved with the proper name (sha1).

        This function is useful if we ever change how the SHA1 is computed. It
        allows us to re-index the local storage and adjust our structures
        without having to re-download all the mail.
    """
    (msgIndex, fldIndex, backupDir) = arg
    progress("\r%s" % dirname)
    for oldSha1 in [f for f in fnames if msgIndex.has_key(f)]:
        msg = msgIndex[oldSha1]
        fp = open(os.path.join(dirname, oldSha1), 'r')

        firstLine = fp.readline()
        if firstLine.startswith('>From - '):
            # Broken headers that will trip up HeaderParser
            pass
        else:
            fp.seek(0)

        parser = HeaderParser()
        pMsg = parser.parse(fp, headersonly=True)
        fp.close()
        sha1 = EmailMsg.computeSha1(msg['internaldate'], pMsg)
        if sha1 != oldSha1:
            # If the message is malformed, the parser could fail here, even
            # though it succeeded in EmailMsg.__init__ because in EmailMsg the
            # full headers were parsed by Google, and here by HeaderParser.
            logger.debug("Mismatch %s vs %s", sha1, oldSha1)
            set_trace()
            fp = open(os.path.join(dirname, oldSha1), 'r')
            parser = HeaderParser()
            pMsg = parser.parse(fp, headersonly=True)
            fp.close()
            sha1 = EmailMsg.computeSha1(msg['internaldate'], pMsg)

            if options.dryRun: continue

            EmailMsg.move(oldSha1, sha1, backupDir)
            msgIndex[sha1] = msg
            del( msgIndex[oldSha1] )
            for folder in msgIndex[sha1]['folder']:
                for UID in [item[0] for item in fldIndex[folder].msgs.items() if item[1] is oldSha1]:
                    fldIndex[folder].msgs[UID] = sha1
        else:
            pass
            #logger.debug("Good match %s %s" % (dirname, sha1))


def houseKeeping(backupDir, msgIndexFile, fldIndexFile, purge):
    msgIndex = deserialize(msgIndexFile)

    if purge:
        status("Purging stale messages\n")
        os.path.walk(backupDir, purgeCallBack, msgIndex)
        status("\n", False)
    else:
        status("Re-indexing local messages\n")
        fldIndex = deserialize(fldIndexFile)
        os.path.walk(backupDir, reindexCallBack, (msgIndex, fldIndex, backupDir))
        status("\n", False)
        if options.dryRun: return
        serialize(msgIndexFile, msgIndex)
        serialize(fldIndexFile, fldIndex)


def createMaildir(backupDir, msgIndexFile, emailAddr, maildir):
    """
    Creates a Maildir type directory and sym-links all the backed-up email
    messages into it so that the mail can be inspected using a mail reader that
    supports Maildir directly (ex: mutt).

    CAVEAT LECTOR: Any modifications made by the mail reader may corrupt the
    backup. BaGoMa will not check for local modifications. Renaming, moving, or
    deleting the sym-links is allowed since that doesn't impact the actual
    backup. MUA's should rename the links to add/remove flags. Pointing an IMAP
    server (ex: Dovecot) to the generated directory has not been tested.

    The filenames follow (loosely) the format specified at:
        http://cr.yp.to/proto/maildir.html
    The timestamp part of the filename is made up. Any MUA that relies on it
    instead of the information in the message headers will not function
    properly.

    @param backupDir The directory containing the backed up email
    @param msgIndexFile
    @param fldIndexFile
    @param emailAddr Used to extract the host/domain name
    @param maildir The path to the Maildir type directory to be created. Must
    not exist, or the function will refuse to overwrite it.
    """

    if os.path.exists(maildir):
        logger.error("Maildir '%s' already exists. Refusing to overwrite." % (maildir))
        return

    msgIndex = deserialize(msgIndexFile)
    hostname = emailMatch.search(emailAddr).group(3).lower()
    timestamp = int(time.time())
    deliveryId = 0
    msgCnt = len(msgIndex)
    flagMap = {'\\Flagged' : 'F', '\\Seen' : 'S'}   # Gmail->Maildir mapping
    status("Creating Maildir '%s' for %d message(s).\n" % (maildir, msgCnt))

    for (sha1, msg) in msgIndex.items():
        srcFile = os.path.abspath( os.path.join(backupDir, sha1[0:2], sha1) )
        if not os.path.exists(srcFile):
            logger.debug("Skipping missing file/email: %s" % (srcFile))
            continue

        flags = list()
        for flag in msg['flags'].split(' '):
            if flag in flagMap.keys():
                flags.append(flagMap[flag])
        flags.sort()    # Flags are supposed to be sorted
        flags = ''.join(flags)

        for folder in msg['folder']:
            if folder == 'INBOX':
                destDir = maildir
            else:
                destDir = os.path.join(maildir, "." + folder.replace('/', '.'))
            if not os.path.exists(os.path.join(destDir, 'cur')):
                for subDir in ('cur', 'new', 'tmp'):
                    os.makedirs(os.path.join(destDir, subDir), mode=0775)
            destDir = os.path.join(destDir, 'cur')
            msgLink = "%d.%06d_0.%s:2,%s" % (timestamp, deliveryId, hostname, flags)
            os.symlink(srcFile, os.path.join(destDir, msgLink))
            timestamp -= 1

        deliveryId += 1
        progress('\r%.0f%% %d/%d ' % (deliveryId * 100.0 /msgCnt, deliveryId, msgCnt))


def interact(msgIndexFile, fldIndexFile):
    global server, options

    msgIndex = deserialize(msgIndexFile)
    fldIndex = deserialize(fldIndexFile)

    if server is None:
        server = ImapServer(options.server, options.port, options.email, options.pwd)

    server.select(server.AllMailFolder, readonly=True)
    banner = '\nBaGoMa server instance is "s"';
    instructions = """
    Hit Ctrl-D to exit interpreter and continue program. Some things to do:

    s.getFolders()
    s.uid('SEARCH', '5:90')
    s.saveMsg(5190, '__Test01', options.backupDir, s.AllMailFolder)
    """
    try:
        from IPython.Shell import IPShellEmbed
        s = server
        ipshell = IPShellEmbed('', banner=banner)
        ipshell(instructions)
    except ImportError:
        import code
        code.interact(banner + "\n" + instructions, local=dict(s=server, options=options, msgIndex=msgIndex, fldIndex=fldIndex))


def optionsFromConfig(options, config):
    """
    Copies missing command line options from the config file. Currently the only
    option that can be missing is the password.
    """
    section = options.email
    if config.has_section(section):
        for key, val in options.__dict__.items():
            if val is None:
                if config.has_option(section, key):
                    options.__dict__[key] = config.get(section, key)


def setupLogging():
    """
    Sets up logging. To use from the code:

    logger.debug("Debug")
    logger.info("Info")
    logger.warn("Warn")
    logger.error("Error")
    logger.exception("from the except block")
    """

    global logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    numericLevel = getattr(logging, options.logLevel.upper(), None)
    if not isinstance(numericLevel, int):
        raise ValueError('Invalid log level: %s' % options.logLevel)

    if numericLevel <= logging.DEBUG:
        imaplib.Debug = 4

    # Log user-defined level to console
    ch = logging.StreamHandler()
    ch.setFormatter( logging.Formatter('%(levelname)-8s %(message)s') )
    ch.setLevel(numericLevel)
    logger.addHandler(ch)

    # Log debug messages to a file
    if len(options.logFile) and options.logFile != 'off':
        rotateFile(options.logFile, 5, move=True)
        fh = logging.FileHandler(options.logFile, "a", encoding = "UTF-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter( logging.Formatter('%(asctime)s - %(name)s - %(levelname)-8s - %(message)s') )
        logger.addHandler(fh)


def main(argv=None):
    global options, server

    if argv is None:
        argv = sys.argv

    usage = "usage: %prog [options] -e <Email>"
    parser = OptionParser(usage = usage)
    parser.add_option("-e", "--email", dest="email",
                        help="The email address to log in with (MANDATORY)")
    parser.add_option("-p", "--pwd", dest="pwd",
                        help="The password to log in with (will prompt if \
                        missing and not present in the config file either)")
    parser.add_option("-d", "--dir", dest="backupDir",
                        help="The backup/restore directory [default: same as email]")
    parser.add_option("-a", "--action", dest="action", default='backup',
                        choices=['backup', 'restore', 'compact', 'printIndex', 'stats', 'maildir', 'debug'],
                        help="The action to perform: backup, restore, stats, maildir, \
                        compact, printIndex or debug [default: %default]")
    parser.add_option("--dryRun", default=False, action="store_true",
                        help="When combined with \"compact\", shows what files \
                        would be deleted [default: %default]")
    parser.add_option("--gui", default=False, action="store_true",
                        help="Used when launched by the GUI.")
    parser.add_option("-s", "--server",
                        default="imap.gmail.com",
                        help="The GMail server to use [default: %default]")
    parser.add_option("--port", default=993,
                        help="The IMAP port to use for GMail [default: %default]")
    parser.add_option("-m", "--maildir", dest="maildir", default="Maildir.BaGoMa",
                        help="Used with the \"maildir\" action to specify where \
                        to create the Maildir directory [default: %default]")
    parser.add_option("-l", "--log", dest="logLevel", default="WARNING",
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="The console log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) [default: %default]")
    parser.add_option("-f", "--file", dest="logFile", default='log.txt',
                        help="The log file (set it to 'off' to disable logging) [default: %default]")
    parser.add_option("-c", "--config", dest="configFile", default=".BaGoMa",
                        help="A configuration file to read settings (the password) from [default: %default]")
    parser.add_option("--version", default=False, action="store_true",
                        help="show the version number")

    (options, args) = parser.parse_args(argv)

    setupLogging()
    logger.debug("**** **** **** **** **** **** **** **** **** **** **** ****")
    logger.debug("Version: %s", __version__)
    logger.debug(pprint.pformat( [i for i in options.__dict__.items() if i[0] != 'pwd'] ))

    config = ConfigParser.ConfigParser()
    if os.path.exists(options.configFile):
        config.read(options.configFile)

    if options.version:
        status("Version: %s\n" % __version__)
        return

    if options.email is None:
        parser.print_help()
        parser.error("option -e is mandatory")

    optionsFromConfig(options, config)

    if options.backupDir is None:
        options.backupDir = options.email

    global progress
    if options.gui:
        progress = progressGui
    else:
        progress = progressCli

    msgIndexFile = os.path.join(options.backupDir, "msgIndex.pickle")
    fldIndexFile = os.path.join(options.backupDir, "fldIndex.pickle")

    server = None
    if options.action == "backup":
        server = ImapServer(options.server, options.port, options.email, options.pwd)
        backup(server, options.backupDir, msgIndexFile, fldIndexFile)
    elif options.action == "restore":
        server = ImapServer(options.server, options.port, options.email, options.pwd)
        restore(server, options.backupDir, msgIndexFile, fldIndexFile)
    elif options.action == "compact":
        houseKeeping(options.backupDir, msgIndexFile, fldIndexFile, True)
        houseKeeping(options.backupDir, msgIndexFile, fldIndexFile, False)
    elif options.action == "printIndex":
        status(deserialize(msgIndexFile))
        status("\n\n")
        status(deserialize(fldIndexFile))
    elif options.action == "stats":
        Stats.extractStats(options.backupDir, msgIndexFile, fldIndexFile)
    elif options.action == "maildir":
        createMaildir(options.backupDir, msgIndexFile, options.email, options.maildir)
    elif options.action == "debug":
        interact(msgIndexFile, fldIndexFile)

    if server is not None:
        try:
            server.close()
            server.logout()
        except:
            logger.exception("Closing server connection")

    status('\nDone.\n')


if __name__ == '__main__':
    sys.exit(main())

