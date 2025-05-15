db = db.getSiblingDB('admin');
db.createUser({
  user: 'vidx',
  pwd: 'vidx',
  roles: [
    { role: 'userAdminAnyDatabase', db: 'admin' },
    { role: 'readWriteAnyDatabase', db: 'admin' },
    { role: 'dbAdminAnyDatabase', db: 'admin' }
  ]
});