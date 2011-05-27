#!/bin/bash

# Adds bagoma.exe (built on a Windows PC) to the zip file

cd dist
if [ ! -f bagoma.exe ]; then
	exit "bagoma.exe missing"
	return 1
fi

P=`ls -1 BaGoMa*.zip | sed -s 's/\.zip$//'`
mkdir -p $P
cp bagoma.exe $P
zip -r $P.zip $P
