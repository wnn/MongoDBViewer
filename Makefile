PYPI = -i http://192.168.18.9/pypi

all: MongoDBViewer.exe

Scripts:
	virtualenv . --no-site-packages --distribute
	Scripts/easy_install.exe $(PYPI) pywin32
	Scripts/easy_install.exe $(PYPI) PySide
	Scripts/easy_install.exe $(PYPI) pymongo

MongoDBViewer.exe: Scripts
	Scripts/python `where pyinstaller.py` MongoDBViewer.spec

clean_dist:
	rm build -rf
	rm dist -rf
	rm warnMongoDBViewer.txt -f
	rm MongoDBViewer.exe -f

clean_extra:
	rm *.log -f
	rm cache -rf

clean_virtualenv:
	rm Include -rf
	rm Lib -rf
	rm Scripts -rf

clean: clean_dist clean_extra clean_virtualenv