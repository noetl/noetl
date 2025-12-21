import os
import psycopg

conn = psycopg.connect(
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@"
    f"{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
)
cur = conn.cursor()
cur.execute('''
SELECT COUNT(*) as count, event_type 
FROM noetl.event 
WHERE parent_execution_id = 513848297795093313 OR execution_id = 513848297795093313 
GROUP BY event_type 
ORDER BY event_type
''')
for row in cur.fetchall():
    print(f"{row[0]} {row[1]}")
