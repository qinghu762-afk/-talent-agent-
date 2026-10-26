from pathlib import Path
p=Path(__file__).parent/'setup_readonly_views.py'
s=p.read_text('utf-8-sig')
s=s.replace("data->>'name' AS name, data->>'location' AS location", "data->'profile'->>'name' AS name, data->'profile'->>'location' AS location")
s=s.replace("(data->>'experience_months')::double precision", "NULLIF(data->'profile'->>'experience_months','')::double precision")
s=s.replace("(data->>'completeness')::double precision", "NULLIF(data->'profile'->>'completeness','')::double precision")
s=s.replace('CREATE OR REPLACE VIEW analytics_learning AS','DROP VIEW IF EXISTS analytics_learning;\nCREATE VIEW analytics_learning AS')
s=s.replace("data->>'status' AS status, data->'progress' AS progress, revision", """data->>'status' AS status,
 CASE WHEN jsonb_typeof((data->'course_ids')::jsonb)='array'
           AND jsonb_array_length((data->'course_ids')::jsonb)>0
 THEN (SELECT COUNT(*)::double precision
       FROM jsonb_array_elements_text((data->'course_ids')::jsonb) AS course(course_id)
       WHERE data->'progress'->course.course_id->>'completed'='true')
      / jsonb_array_length((data->'course_ids')::jsonb)
 ELSE 0.0 END AS progress, revision""")
p.write_text(s,encoding='utf-8')
p=Path(__file__).parent/'generate_compose.py';s=p.read_text('utf-8-sig')
s=s.replace("if name=='init_permissions': service['volumes']=['dify-storage:/app/api/storage']", "if name=='init_permissions':\n        service['image']='busybox@sha256:dc2d74b28e4cf8984fa52af1f39bc7c3d9c73760b41a74d629f5d11b1ab28616'\n        service['volumes']=['dify-storage:/app/api/storage']")
s=s.replace("agent=name=='agent_ssrf_proxy'", "agent=name=='agent_ssrf_proxy'\n        service['image']='ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029'")
p.write_text(s,encoding='utf-8')
