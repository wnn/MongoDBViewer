# -*- mode: python -*-
a = Analysis(scripts=[os.path.join(HOMEPATH,'support\\_mountzlib.py'),
                      os.path.join(HOMEPATH,'support\\useUnicode.py'),
                      'gui.py'])
pyz = PYZ(a.pure)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='MongoDBViewer.exe',
          icon='favicon.ico',
          debug=False,
          strip=False,
          upx=True,
          console=True )
