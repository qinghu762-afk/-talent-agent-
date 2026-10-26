"""Create analytics views after ORM initialization; never grant source tables."""
import json
import sys
import psycopg
import pymysql

PG_SQL = '''
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM talent_readonly;
CREATE OR REPLACE VIEW analytics_talents AS
 SELECT id, org_id, data->'profile'->>'name' AS name, data->'profile'->>'location' AS location,
 NULLIF(data->'profile'->>'experience_months','')::double precision AS experience_months,
 NULLIF(data->'profile'->>'completeness','')::double precision AS completeness, revision
 FROM records WHERE kind='talents' AND COALESCE(data->>'deleted','false')<>'true';
CREATE OR REPLACE VIEW analytics_assessments AS
 SELECT id, org_id, data->>'talent_id' AS talent_id, data->>'title' AS title,
 data->>'status' AS status, (data->>'total')::double precision AS total, revision
 FROM records WHERE kind='assessments' AND COALESCE(data->>'deleted','false')<>'true';
DROP VIEW IF EXISTS analytics_learning;
CREATE VIEW analytics_learning AS
 SELECT id, org_id, data->>'talent_id' AS talent_id, data->>'title' AS title,
 data->>'status' AS status,
 CASE WHEN jsonb_typeof((data->'course_ids')::jsonb)='array'
           AND jsonb_array_length((data->'course_ids')::jsonb)>0
 THEN (SELECT COUNT(*)::double precision
       FROM jsonb_array_elements_text((data->'course_ids')::jsonb) AS course(course_id)
       WHERE data->'progress'->course.course_id->>'completed'='true')
      / jsonb_array_length((data->'course_ids')::jsonb)
 ELSE 0.0 END AS progress, revision
 FROM records WHERE kind='training-plans' AND COALESCE(data->>'deleted','false')<>'true';
GRANT SELECT ON analytics_talents, analytics_assessments, analytics_learning TO talent_readonly;
'''
MYSQL_SQL = '''CREATE OR REPLACE SQL SECURITY DEFINER VIEW analytics_jobs AS
 SELECT id, org_id, JSON_UNQUOTE(JSON_EXTRACT(data,'$.title')) AS title, revision
 FROM resources WHERE kind='jobs' AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(data,'$.deleted')),'false')<>'true' '''


def main():
    credentials=json.load(sys.stdin)
    with psycopg.connect(host='postgres',dbname='talent_analytics',user='talent_analytics',password=credentials['ANALYTICS_PASSWORD']) as db:
        db.execute(PG_SQL)
    with pymysql.connect(host='mysql',database='talent',user='root',password=credentials['MYSQL_ROOT_PASSWORD'],charset='utf8mb4') as db:
        with db.cursor() as cur:
            cur.execute(MYSQL_SQL)
            cur.execute("GRANT SELECT ON talent.analytics_jobs TO 'talent_readonly'@'%'")
        db.commit()
    print('Analytics accounts have access only to the declared safe views.')


if __name__=='__main__':main()
