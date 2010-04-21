.PHONY: clean install dist doc win
PROJECT=BaGoMa

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
	pandoc -s --to=html README -o doc/index.html

dist: doc
	python setup.py sdist
	python setup.py bdist_egg
	#python setup.py bdist

win: doc
	python setup.py bdist_wininst
	#python setup.py bdist_msi

deb: dist
	# TODO:
	#rename -f 's/$(PROJECT)-(.*)\.tar\.gz/$(PROJECT)_$$1\.orig\.tar\.gz/' dist/*.tar.gz
	#cp -r debian dist/
	#cd dist && dpkg-buildpackage -i -I -rfakeroot
