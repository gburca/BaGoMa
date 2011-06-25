#!/usr/bin/env python3
# vi:ai:tabstop=8:shiftwidth=4:softtabstop=4:expandtab:fdm=indent

"""
A GUI for:

BaGoMa - BAckup GOogle MAil - A Smart GMail Backup Script
"""

__version__ = "1.00"
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

from tkinter import *
from tkinter import ttk, filedialog
from subprocess import PIPE, Popen
import sys, os, traceback
from threading import Thread
from queue import Queue, Empty
import platform

ON_POSIX = 'posix' in sys.builtin_module_names

class MonitorOutput(object):
    """
    This class monitors the output of a process, queues it, and provides a way
    to access it at a later time
    """

    def __init__(self, pipe):
        self.q = Queue()
        self.t = Thread(target=MonitorOutput.enqueue, args=(pipe, self.q))
        # Make the thread die with the process
        self.t.daemon = True
        self.t.start()

    @staticmethod
    def enqueue(src, queue):
        for line in src:
            queue.put(line.decode('utf-8'))
        src.close()

    def getLine(self):
        try:
            line = self.q.get_nowait()
        except Empty:
            return None
        else:
            self.q.task_done()
            return line


class App:
    def __init__(self, root):
        self.root = root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        frame = ttk.Frame(root, padding="3 3 3 3")
        frame.grid(column=0, row=0, sticky=(N, W, E, S))

        self.mkEmailPwd(frame).grid(column=0, row=0, sticky=(W, E))
        self.mkBkupDir(frame).grid(column=0, row=1, sticky=(W, E))
        self.mkButtons(frame).grid(column=0, row=2, sticky=(W, E))
        self.mkStatus(frame).grid(column=0, row=3, sticky=(N, W, E, S), padx=5, pady=5)

        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)


    def mkEmailPwd(self, root):
        f = ttk.Frame(root)

        ttk.Label(f, text="E-Mail:").grid(column=0, row=0, sticky=W)
        ttk.Label(f, text="Password:").grid(column=1, row=0, sticky=W)

        self.email = StringVar()
        self.pwd = StringVar()

        self.emailE = ttk.Entry(f, textvariable=self.email)
        self.emailE.grid(column=0, row=1, sticky=(W, E))

        self.pwdE = ttk.Entry(f, textvariable=self.pwd, show="*")
        self.pwdE.grid(column=1, row=1, sticky=(W, E))

        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)
        self.addPadding(f, 5, 0)
        self.emailE.focus()
        return f

    def mkBkupDir(self, root):
        f = ttk.Frame(root)

        ttk.Label(f, text="Backup directory:").grid(column=0, row=0, sticky=W)
        self.bkupDir = StringVar()
        bkupDirE = ttk.Entry(f, textvariable=self.bkupDir)
        bkupDirE.grid(column=0, row=1, sticky=(W, E))

        dirB = ttk.Button(f, text="...", padding="0", width=1, command=lambda: self.chooseDir())
        dirB.grid(column=1, row=1, sticky=(W, E))
        
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=0)
        self.addPadding(f, 5, 0)

        return f


    def mkButtons(self, root):
        buttonsF = ttk.Frame(root)

        bkupI = PhotoImage(file=os.path.join(self.getHomeDir(), 'img', 'backup.gif'))
        restoreI = PhotoImage(file=os.path.join(self.getHomeDir(), 'img', 'restore.gif'))

        self.bkupB      = ttk.Button(buttonsF, compound=TOP, text="Backup", image=bkupI, command=lambda: self.backup())
        self.restoreB   = ttk.Button(buttonsF, compound=TOP, text="Restore", image=restoreI, command=lambda: self.restore())
        self.bkupB.grid(column=0, row=0, sticky=E)
        self.restoreB.grid(column=1, row=0, sticky=W)
        # Needed to prevent image garbage collection
        self.bkupB.image = bkupI
        self.restoreB.image = restoreI

        self.addPadding(buttonsF, 20, 10)
        buttonsF.columnconfigure(0, weight=1)
        buttonsF.columnconfigure(1, weight=1)
        return buttonsF

    def mkStatus(self, root):
        f = ttk.Frame(root)

        ttk.Label(f, text="Progress status:").grid(column=0, row=0, sticky=W)
        self.statusT = Text(f)
        self.statusT.grid(column=0, row=1, sticky=(N, W, E, S))
        self.statusT.tag_configure('stdout', foreground='black', wrap='none')
        self.statusT.tag_configure('stderr', foreground='red', wrap='none')
        self.statusT.tag_configure('msg', foreground='blue', wrap='none')
        self.statusT.config(state=DISABLED)

        scrollY = ttk.Scrollbar(f, orient=VERTICAL,   command=self.statusT.yview)
        scrollX = ttk.Scrollbar(f, orient=HORIZONTAL, command=self.statusT.xview)
        self.statusT.configure(yscrollcommand=scrollY.set)
        self.statusT.configure(xscrollcommand=scrollX.set)
        scrollY.grid(column=1, row=1, sticky=(N, S))
        scrollX.grid(column=0, row=2, sticky=(E, W))

        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=0)
        f.rowconfigure(0, weight=0)
        f.rowconfigure(1, weight=1)
        f.rowconfigure(2, weight=0)
        return f

    def addPadding(self, frame, padx, pady):
        for child in frame.winfo_children():
            child.grid_configure(padx=padx, pady=pady)
        

    def chooseDir(self):
        dir = filedialog.askdirectory(title='Please select the backup directory')
        if dir: self.bkupDir.set(dir)

    def checkOutput(self, proc, mOut, mErr):
        """Check stdout and stderr for data, and add it to the status window"""
        lines = 0

        while (not mOut.q.empty()) or (not mErr.q.empty()):
            line = mOut.getLine()
            if line:
                lines += 1
                self.addStatusT(line, 'stdout')
            line = mErr.getLine()
            if line:
                lines += 1
                self.addStatusT(line, 'stderr')

            #if lines % 100 == 0:
            #    self.statusT.see(END)   # Scroll display
            #    self.root.update()

        self.statusT.see(END)   # Scroll display

        if proc.poll() is None or not mOut.q.empty() or not mErr.q.empty():
            self.root.after(100, self.checkOutput, proc, mOut, mErr)
        else:
            self.buttonsEnabled(True)


    def addStatusT(self, line, style = None):
        """Add a line of data to the status window, handling carriage-return
        similar to how the terminal does (over-writing current line)"""
        self.statusT.config(state=NORMAL)
        if style is None: style = 'stdout'
        if line.startswith('\r'):
            line = line.strip()
            prevEnd = self.statusT.get(str(END) + "-1 lines linestart", END)
            if prevEnd == '\n':
                self.statusT.delete(str(END) + "-1 lines linestart + 1 c", END)
                self.statusT.insert(END, line, style)
            else:
                self.statusT.delete(str(END) + "-1 lines linestart", END)
                self.statusT.insert(END, "\n" + line, style)
        else:
            self.statusT.insert(END, line, style)

        self.statusT.config(state=DISABLED)
        self.statusT.see(END)   # Scroll display


    def checkArgs(self):
        if len(self.email.get().strip()) == 0:
            self.addStatusT("Email required\n", 'stderr')
            self.emailE.focus()
            return False
        if len(self.pwd.get()) == 0:
            self.addStatusT("Password required\n", 'stderr')
            self.pwdE.focus()
            return False
        self.bkupDir.set( self.bkupDir.get().strip() )
        return True


    def buttonsEnabled(self, enabled):
        if enabled:
            self.bkupB   .config(state=NORMAL)
            self.restoreB.config(state=NORMAL)
        else:
            self.bkupB   .config(state=DISABLED)
            self.restoreB.config(state=DISABLED)


    def backup(self):
        if not self.checkArgs(): return
        cmd_line = ['--gui', '-a', 'backup', '-e', self.email.get(), '-p', self.pwd.get()]
        if self.bkupDir.get():
            cmd_line.extend(['--dir', self.bkupDir.get()])
        self.execute(cmd_line)


    def restore(self, *args):
        if not self.checkArgs(): return
        cmd_line = ['--gui', '-a', 'restore', '-e', self.email.get(), '-p', self.pwd.get()]
        if self.bkupDir.get():
            cmd_line.extend(['--dir', self.bkupDir.get()])
        self.execute(cmd_line)

    def getHomeDir(self):
        if os.path.isfile(sys.path[0]):
            # This is the case for gui.exe
            homeDir = os.path.dirname(sys.path[0])
        else:
            homeDir = sys.path[0]
        return homeDir

    def execute(self, cmd_line):
        """Execute a command, and display its output in the status window"""
        try:
            self.buttonsEnabled(False)
            self.statusT.config(state=NORMAL)
            self.statusT.delete(1.0, END)
            self.statusT.config(state=DISABLED)

            exe = os.path.join(self.getHomeDir(), 'bagoma.exe')
            if platform.system() == 'Windows':
#                if os.path.isfile(exe):
#                    cmd_line.insert(0, exe)
#                else:
#                    cmd_line.insert(0, 'bagoma.py')
#                    cmd_line.insert(0, 'python')
                cmd_line.insert(0, exe)
            else:
                cmd_line.insert(0, os.path.join(self.getHomeDir(), 'bagoma.py'))

            self.addStatusT("Executing: " + ' '.join(cmd_line) + "\n", 'msg')

            proc = Popen(cmd_line, bufsize=1, stdout=PIPE, stderr=PIPE, close_fds=ON_POSIX)
            mOut = MonitorOutput(proc.stdout)
            mErr = MonitorOutput(proc.stderr)

            self.checkOutput(proc, mOut, mErr)
        except:
            self.addStatusT(traceback.format_exc(), 'stderr')
            self.buttonsEnabled(True)


root = Tk()
root.title("BaGoMa")
app = App(root)

root.mainloop()

