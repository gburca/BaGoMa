#!/usr/bin/env python
# vi:ai:tabstop=8:shiftwidth=4:softtabstop=4:expandtab:fdm=indent

"""
BaGoMa - BAckup GOogle MAil - A Smart GMail Backup Script

See the README file for full details. Run the script with no arguments to see
the available options.
"""

__version__ = "1.10"
__author__ = "Gabriel Burca (gburca dash bagoma at ebixio dot com)"
__copyright__ = "Copyright (C) 2010-2011 Gabriel Burca. Code under GPL License."
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
import re
import pprint
import hashlib
import time
import getpass
from optparse import OptionParser
from email.parser import HeaderParser

# For debugging
try:
    import pdb
except ImportError:
    set_trace = lambda: 0
else:
    set_trace = pdb.set_trace

import logging
from types import *

options = None

# Special Google folder FLAGS we should ignore (Spam, Trash, Drafts, etc...)
IgnoredFolderFlags = set(['\\Spam', '\\Trash'])

# Folders to ignore (some EMail clients create their own Trash, etc...)
IgnoredFolders = ['Spam', 'Trash']

# Tell imaplib that XLIST works the same way as LIST
imaplib.Commands['XLIST'] = imaplib.Commands['LIST']

msgIdMatch  = re.compile(r'\bMessage-Id\: (.+)', re.IGNORECASE + re.MULTILINE)
uIdMatch    = re.compile(r'\bUID (\d+)', re.IGNORECASE)
lstRspMatch = re.compile(r'\((?P<flags>.*?)\) "(?P<delimiter>.*)" (?P<name>.*)')
intDateMatch= re.compile(r'\bINTERNALDATE "([^"]+)"')
flagsMatch  = re.compile(r'\bFLAGS \(([^\)]*)\)')


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
    if type(msg) in [StringType, IntType, LongType, FloatType]:
        sys.stdout.write(msg)
        if log2logger: logger.info(str(msg).strip())
    else:
        msgStr = pprint.pformat(msg)
        sys.stdout.write(msgStr)
        if log2logger: logger.info(msgStr.strip())
    sys.stdout.flush()


class ImapServer(imaplib.IMAP4_SSL):
    def __init__(self, serverAddr, serverPort, email, pwd):
        if pwd is None:
            pwd = getpass.getpass()

        logger.info('Connecting to %s ...', options.server)
        imaplib.IMAP4_SSL.__init__(self, serverAddr, serverPort)

        logger.info('Logging in as %s ...', email)
        self.login(email, pwd)

        # Discover the special folders (which change with country):
        # [Gmail]/All Mail  = \AllMail
        # [Gmail]/Trash     = \Trash
        # [Gmail]/Spam      = \Spam
        # [Gmail]/Drafts    = \Drafts

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


    def upload(self, cacheDir, msg, destFolder):
        """
        Finds the file containing the msg, and uploads it to the destFolder on the server.

        Returns the new UID assigned to the uploaded message, or None if it fails.
        """
        sha = msg['sha1']
        fullPath = os.path.join(cacheDir, sha[0:2], sha)
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


    def saveMsg(self, uid, shaHex, cacheDir, folderName=None):
        """
        Saves a mail message locally. If cacheDir does not exist, nothing is saved.

        @param uid The UID of the message to save
        @param shaHex The sha/file to save it to
        @param cacheDir The directory to save it to
        @param folderName Optional name of the IMAP folder to retrieve the
            message from. If the folderName argument is not used, the folder to
            save from should be selected before calling this method.
        """

        if cacheDir is None or not os.path.exists(cacheDir):
            return False

        dir = os.path.join(cacheDir, shaHex[0:2])
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
            logger.warn("File %s already exists" % (shaHex))

        return False


    def saveAllMsgs(self, cacheDir, oldMsgs, oldFlds):
        """
        Saves all new messages to the cacheDir.

        @param cacheDir The directory to save the messages in
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
        status("Retained %d message(s). Need to D/L %d new message(s).\n" % (len(messages), msgCnt))
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
                    self.saveMsg(uid, dupSha1, cacheDir)
                    logger.warn("Duplicate SHA1 found. UID: %s & %s. Saved to SHA1: %s" % (old['uid'], uid, dupSha1))
                    logger.debug("InternalDate: %s -- %s" % (old['internaldate'], msg['internaldate']))
                else:
                    if not oldMsgs.has_key(sha1):
                        self.saveMsg(uid, sha1, cacheDir)
                        saved += 1
                    messages[sha1] = msg
                    folder.msgs[uid] = sha1

                status('\r%d/%d ' % (i, msgCnt), False)
        except:
            status("\n", False)
            logger.debug("Saved %d/%d messages (%d candidates)" % (saved, msgCnt, i))
            logger.exception("Could not save all messages")

        if len(messages) < 20:
            logger.debug(pprint.pformat(messages))
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
                folder = self.indexOneFolder(messages, oldFlds.get(folderName, None), folderName)

                if folder is not None:
                    folderInfo[folderName] = folder
                else:
                    # TODO: Error handling
                    continue
        except:
            logger.exception("Could not index all folders.")

        return (folderInfo, messages)


    def indexOneFolder(self, messages, oldFld, folderName):
        """
        messages    could be None
        oldFld      could be None - results in full indexing
        """
        folder = EmailFolder(self, folderName)
        if folder.OK:
            status("Indexing: %s\n" % folderName)
        else:
            # TODO: Error handling
            logger.error("Unable to select folder: %s" % folderName)
            return None

        if folder.sameUidVal(oldFld):
            msgUIDs = folder.carryOver(oldFld, messages, None)
        else:
            msgUIDs = folder.UIDs

        msgCnt = len(msgUIDs)
        status("Retained %d message(s). Need to transfer %d message(s).\n" % (len(folder.msgs), msgCnt))
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
                    if messages.has_key(msg['sha1']):
                        messages[msg['sha1']]['folder'].append(folderName)
                    else:
                        # Assumes saveAllMsgs was called first, and messages
                        # contains a full list of all current SHA1's
                        logger.warn("New message arrived in %s while indexing %d/%d ?" % (folderName, i, msgCnt))

                status('\r%d/%d ' % (i, msgCnt), False)
        except:
            status("\n", False)
            logger.debug("Indexed %d/%d" % (i, msgCnt))
            logger.exception("Could not index folder %s" % folderName)

        status("\n", False)
        return folder


class EmailFolder(dict):
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
        #FLAGS = server.response('FLAGS')[1][0].strip(')(')
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
        shaLst = (internaldate,
            ' '.join(m.get('from', "").split()),
            ' '.join(m.get('to', "").split()),
            ' '.join(m.get('cc', "").split()),
            ' '.join(m.get('date', "").split()),
            ' '.join(m.get('subject', "").split()),
            ' '.join(m.get('x-gmail-received', "").split()),
            ' '.join(m.get('message-id', "").split()) )

        return hashlib.sha1("\n".join(shaLst)).hexdigest()


    @staticmethod
    def move(shaHexFrom, shaHexTo, cacheDir):
        srcPath = os.path.join(cacheDir, shaHexFrom[0:2], shaHexFrom)
        dstPath = os.path.join(cacheDir, shaHexTo[0:2], shaHexTo)

        # Creates directories as needed
        os.renames(srcPath, dstPath)


def backup(server, cacheDir, msgIndexFile, fldIndexFile):
    """
    Backs up the current state of the server. All messages are saved in
    cacheDir, and metadata goes in the msgIndexFile and fldIndexFile.
    """

    # If cacheDir does not exist, nothing is saved, so create it first.
    if not os.path.exists(cacheDir):
        os.makedirs(cacheDir)

    oldMsgs = deserialize(msgIndexFile)
    oldFlds = deserialize(fldIndexFile)
    messages, allMailFld = server.saveAllMsgs(cacheDir, oldMsgs, oldFlds)
    if len(messages) >= 0:
        # Save msgIndex first, in case we run into problems later
        if len(msgIndexFile) > 0: serialize(msgIndexFile, messages)

        newFlds, messages = server.indexAllFolders(messages, oldFlds, allMailFld)

        if len(msgIndexFile) > 0: serialize(msgIndexFile, messages)
        if len(fldIndexFile) > 0: serialize(fldIndexFile, newFlds)

        if len(messages) < 20:
            logger.debug(pprint.pformat(messages))
    else:
        logger.info("Not enough messages to back up")


def restore(server, cacheDir, msgIndexFile, fldIndexFile):
    """
    Restores messages from the local backup. For messages that are already on
    the server, it restores the labels that were attached to the message when
    the backup was made.
    """
    if not os.path.exists(cacheDir) or not os.path.exists(msgIndexFile) or not os.path.exists(fldIndexFile):
        return False

    oldMsgs = deserialize(msgIndexFile)
    oldFlds = deserialize(fldIndexFile)

    if not restoreAllMailFld(server, cacheDir, oldMsgs, oldFlds[server.AllMailFolder]):
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

 

def restoreAllMailFld(server, cacheDir, oldMsgs, oldFld):
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
            newUid = server.upload(cacheDir, oldMsgs[sha1], server.AllMailFolder)
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
            newUid = server.upload(cacheDir, oldMsgs[sha1], server.AllMailFolder)
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
    for fname in [f for f in fnames if not f.endswith('.pickle')]:
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
    (msgIndex, fldIndex, cacheDir) = arg
    for oldSha1 in [f for f in fnames if not f.endswith('.pickle') and msgIndex.has_key(f)]:
        msg = msgIndex[oldSha1]
        fp = open(os.path.join(dirname, oldSha1), 'r')
        parser = HeaderParser()
        pMsg = parser.parse(fp, headersonly=True)
        sha1 = EmailMsg.computeSha1(msg['internaldate'], pMsg)
        if sha1 != oldSha1:
            logger.debug("Mismatch %s vs %s", sha1, oldSha1)
            if options.dryRun: continue

            EmailMsg.move(oldSha1, sha1, cacheDir)
            msgIndex[sha1] = msg
            del( msgIndex[oldSha1] )
            for folder in msgIndex[sha1]['folder']:
                for UID in [item[0] for item in fldIndex[folder].msgs.items() if item[1] is oldSha1]:
                    fldIndex[folder].msgs[UID] = sha1
        else:
            pass
            #logger.debug("Good match %s %s" % (dirname, sha1))


def houseKeeping(cacheDir, msgIndexFile, fldIndexFile, purge):
    msgIndex = deserialize(msgIndexFile)

    if purge:
        os.path.walk(cacheDir, purgeCallBack, msgIndex)
    else:
        fldIndex = deserialize(fldIndexFile)
        os.path.walk(cacheDir, reindexCallBack, (msgIndex, fldIndex, cacheDir))
        if options.dryRun: return
        serialize(msgIndexFile, msgIndex)
        serialize(fldIndexFile, fldIndex)


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
        fh = logging.FileHandler(options.logFile)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter( logging.Formatter('%(asctime)s - %(name)s - %(levelname)-8s - %(message)s') )
        logger.addHandler(fh)


def main(argv=None):
    if argv is None:
        argv = sys.argv

    usage = "usage: %prog [options] -e <Email>"
    parser = OptionParser(usage = usage)
    parser.add_option("-e", "--email", dest="email",
                        help="the email address to log in with (MANDATORY)")
    parser.add_option("-p", "--pwd", dest="pwd",
                        help="the password to log in with (will prompt if missing)")
    parser.add_option("-d", "--dir", dest="cacheDir",
                        help="the backup/restore directory [default: same as email]")
    parser.add_option("-a", "--action", dest="action", default='backup',
                        choices=['backup', 'restore', 'compact', 'printIndex', 'debug'],
                        help="the action to perform: backup, restore, compact or printIndex [default: %default]")
    parser.add_option("-s", "--server",
                        default="imap.gmail.com",
                        help="the GMail server to use [default: %default]")
    parser.add_option("--dryRun", default=False, action="store_true",
                        help="pretend to perform \"compact\" [default: %default]")
    parser.add_option("--port", default=993,
                        help="the IMAP port to use for GMail [default: %default]")
    parser.add_option("-l", "--log", dest="logLevel", default="WARNING",
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="the console log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) [default: %default]")
    parser.add_option("-f", "--file", dest="logFile", default='log.txt',
                        help="the log file (set it to 'off' to disable logging) [default: %default]")
    parser.add_option("--version", default=False, action="store_true", 
                        help="show the version number")

    global options
    (options, args) = parser.parse_args(argv)
    setupLogging()
    logger.debug("**** **** **** **** **** **** **** **** **** **** **** ****")
    logger.debug("Version: %s", __version__)
    logger.debug(pprint.pformat( [i for i in options.__dict__.items() if i[0] != 'pwd'] ))

    if options.version:
        status("Version: %s\n" % __version__)
        return

    if options.email is None:
        parser.print_help()
        parser.error("option -e is mandatory")

    if options.cacheDir is None:
        options.cacheDir = options.email

    msgIndexFile = os.path.join(options.cacheDir, "msgIndex.pickle")
    fldIndexFile = os.path.join(options.cacheDir, "fldIndex.pickle")

    global server
    server = None
    if options.action == "backup":
        server = ImapServer(options.server, options.port, options.email, options.pwd)
        backup(server, options.cacheDir, msgIndexFile, fldIndexFile)
    elif options.action == "restore":
        server = ImapServer(options.server, options.port, options.email, options.pwd)
        restore(server, options.cacheDir, msgIndexFile, fldIndexFile)
    elif options.action == "compact":
        houseKeeping(options.cacheDir, msgIndexFile, fldIndexFile, True)
        houseKeeping(options.cacheDir, msgIndexFile, fldIndexFile, False)
    elif options.action == "printIndex":
        status(deserialize(msgIndexFile))
        status("\n\n")
        status(deserialize(fldIndexFile))
    else:
        pass
        # Debug
        # server = ImapServer(options.server, options.port, options.email, options.pwd)
        # status(server.getFolders())
        # status(server.select(server.AllMailFolder, readonly=True))
        # status(server.uid('SEARCH', '%d:%d' % (1, 4)))
        # status(server.uid('SEARCH', '5:90'))
        # status(server.saveMsg(5190, "__Duplicate5190", options.cacheDir, server.AllMailFolder))

    if server is not None:
        try:
            server.close()
            server.logout()
        except:
            logger.exception("Closing server connection")

    status('Done.\n')


if __name__ == '__main__':
    sys.exit(main())

