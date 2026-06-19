import time
from app.infrastructure.persistence.mysql import mysql_manager
print('ensure_database start', flush=True)
t0=time.time()
mysql_manager._ensure_database()
print('ensure_database done', round(time.time()-t0,2), flush=True)
print('ensure_pool start', flush=True)
t1=time.time()
mysql_manager._ensure_pool()
print('ensure_pool done', round(time.time()-t1,2), flush=True)
print('ensure_schema start', flush=True)
t2=time.time()
mysql_manager._ensure_schema()
print('ensure_schema done', round(time.time()-t2,2), flush=True)
