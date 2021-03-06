all: MongoDBViewer.exe

Scripts:
	virtualenv . --no-site-packages --distribute
	Scripts/easy_install.exe pywin32
	Scripts/easy_install.exe PySide
	Scripts/easy_install.exe pymongo

MongoDBViewer.exe: Scripts
	Scripts/python.exe `where pyinstaller.py` MongoDBViewer.spec

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