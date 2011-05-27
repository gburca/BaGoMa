.PHONY: clean install dist doc win
PROJECT=BaGoMa
WIN_PYTHON=/cygdrive/c/Utility/Python271

clean:
	python setup.py clean
	rm -rf dist build BaGoMa.egg-info man doc

install:
	python setup.py install

doc:
	mkdir -p man
	pandoc -s --to=man README -o man/bagoma.1
	mkdir -p doc
	pandoc -s --to=plain README -o doc/README.txt
	pandoc -s --to=markdown README -o doc/README.markdown
	pandoc -s --to=html README -o doc/index.html --css=default.css --include-in-header google.analytics

dist: doc
	python setup.py sdist --formats=gztar,zip
	#python setup.py bdist_egg
	#python setup.py bdist

win:
	$(WIN_PYTHON)/python setup-py2exe.py py2exe
	# w9xpopen only needed for Win9x.
	rm -f dist/w9xpopen.exe
	#$(WIN_PYTHON)/python setup.py bdist_wininst
	#$(WIN_PYTHON)/python setup.py bdist_msi

deb: dist
	# TODO:
	#rename -f 's/$(PROJECT)-(.*)\.tar\.gz/$(PROJECT)_$$1\.orig\.tar\.gz/' dist/*.tar.gz
	#cp -r debian dist/
	#cd dist && dpkg-buildpackage -i -I -rfakeroot

upload: dist
	scp homepage/index.html $(USER),bagoma@web.sourceforge.net:htdocs
	scp homepage/default.css $(USER),bagoma@web.sourceforge.net:htdocs

