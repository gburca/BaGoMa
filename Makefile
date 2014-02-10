.PHONY: clean install dist doc win upload
PROJECT=BaGoMa
WIN_PYTHON27=/cygdrive/c/Utility/Python274
WIN_PYTHON32=/cygdrive/c/Utility/Python32

clean:
	python setup.py clean
	rm -rf dist build BaGoMa.egg-info man doc *.pyc

install:
	python setup.py install

doc:
	mkdir -p man
	cat src.doc/man.title README | pandoc -s --to=man -o man/bagoma.1
	mkdir -p doc
	cat src.doc/html.title README | pandoc -s --to=html -o doc/index.html -T "BaGoMa" --css=default.css --include-in-header src.doc/google.analytics
	pandoc -s --to=plain README -o doc/README.txt
	pandoc -s --to=markdown README -o doc/README.markdown --no-wrap

dist: doc
	python setup.py sdist --formats=gztar,zip
	#python setup.py bdist_egg
	#python setup.py bdist

win:
	$(WIN_PYTHON27)/python install/setup-py2exe.py py2exe
	# w9xpopen only needed for Win9x.
	rm -f dist/w9xpopen.exe
	#$(WIN_PYTHON)/python setup.py bdist_wininst
	#$(WIN_PYTHON)/python setup.py bdist_msi

# Builds the GUI portion for Windows. This only works with cx_Freeze since
# py2exe does not support Python 3 at this time (2011-07-12).
#
# In WinXP, install Python 3.2 from ActiveState, then install cx_Freeze:
# C:\>pypm -g install cx_Freeze
win-gui: win
	mkdir -p dist/img
	#cxfreeze.bat gui.pyw --target-dir dist --base-name Win32GUI
	$(WIN_PYTHON32)/python install/setup-cxFreeze.py build
	cp img/*.gif dist/img
	cp -R dist/* build/exe.win32-3.2

deb: dist
	# TODO:
	#rename -f 's/$(PROJECT)-(.*)\.tar\.gz/$(PROJECT)_$$1\.orig\.tar\.gz/' dist/*.tar.gz
	#cp -r debian dist/
	#cd dist && dpkg-buildpackage -i -I -rfakeroot

upload: doc
	scp homepage/index.html homepage/default.css $(USER),bagoma@web.sourceforge.net:htdocs

