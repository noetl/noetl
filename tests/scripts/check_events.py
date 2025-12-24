import os
import psycopg
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')

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
    logger.info(f"{row[0]} {row[1]}")
