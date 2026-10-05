import os
path = os.path.join('instance', 'ecopulse.db')
if os.path.exists(path):
    os.remove(path)
    print('removed', path)
else:
    print('not found', path)

journal = os.path.join('instance', 'ecopulse.db-journal')
if os.path.exists(journal):
    os.remove(journal)
    print('removed', journal)
else:
    print('not found', journal)
