import mysql.connector
from app.config import mysql_config
conn=mysql.connector.connect(host=mysql_config.host, port=mysql_config.port, user=mysql_config.user, password=mysql_config.password, database='information_schema', connection_timeout=5)
cur=conn.cursor()
cur.execute('SHOW PROCESSLIST')
rows=cur.fetchall()
for row in rows:
    print(row)
conn.close()
