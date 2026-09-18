import httpx

client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=30.0)

# 1. Login
login_res = client.post('/auth/login', json={'email': 'admin@dental-ai.com', 'password': 'demo-password'})
assert login_res.status_code == 200, f'Login failed: {login_res.text}'
token = login_res.json()['token']
auth_hdr = {'Authorization': f'Bearer {token}'}
print('[PASS] 1. Auth Login: success, token generated')

# 2. List projects
projs_res = client.get('/projects', headers=auth_hdr)
assert projs_res.status_code == 200
projects = projs_res.json()
p10 = next((p for p in projects if p['id'] == 10), None)
assert p10 is not None, 'Project 10 not found'
assert p10['status'] == 'ready', f'Project 10 not ready: {p10}'
print(f"[PASS] 2. Projects List: found Project 10 ({p10['name']}) status: {p10['status']}")

# 3. Project Summary
summary_res = client.get('/projects/10/summary', headers=auth_hdr)
assert summary_res.status_code == 200
summary_data = summary_res.json()
assert 'summary' in summary_data and bool(summary_data['evidence'])
print('[PASS] 3. Project Overview / Summary: generated with evidence')

# 4. Mandatory 6 Q&A queries
q1 = client.post('/projects/10/ask', headers=auth_hdr, json={'question': 'What is this application used for?'}).json()
assert q1['status'] == 'SUCCESS', q1
print('[PASS] 4.1 Q1 Purpose: SUCCESS')

q2 = client.post('/projects/10/ask', headers=auth_hdr, json={'question': 'How does a missing-person report get submitted?'}).json()
assert q2['status'] == 'SUCCESS', q2
print('[PASS] 4.2 Q2 Report Submit: SUCCESS')

q3 = client.post('/projects/10/ask', headers=auth_hdr, json={'question': 'What happens after a report is submitted?'}).json()
assert q3['status'] == 'SUCCESS', q3
print('[PASS] 4.3 Q3 Post-submission: SUCCESS')

q4 = client.post('/projects/10/ask', headers=auth_hdr, json={'question': 'How does purchase order approval work?'}).json()
assert q4['status'] == 'INSUFFICIENT_EVIDENCE' and q4['evidence'] == [], q4
print('[PASS] 4.4 Q4 PO Approval: INSUFFICIENT_EVIDENCE (evidence=[])')

q5 = client.post('/projects/10/ask', headers=auth_hdr, json={'question': 'How is an invoice generated?'}).json()
assert q5['status'] == 'INSUFFICIENT_EVIDENCE' and q5['evidence'] == [], q5
print('[PASS] 4.5 Q5 Invoice Gen: INSUFFICIENT_EVIDENCE (evidence=[])')

q6 = client.post('/projects/10/ask', headers=auth_hdr, json={'question': 'How does inventory get updated?'}).json()
assert q6['status'] == 'INSUFFICIENT_EVIDENCE' and q6['evidence'] == [], q6
print('[PASS] 4.6 Q6 Inventory Update: INSUFFICIENT_EVIDENCE (evidence=[])')

# 5. Trace Flow
tf_pos = client.post('/projects/10/trace-flow', headers=auth_hdr, json={'question': 'How does a missing-person report get submitted?'}).json()
assert tf_pos['status'] == 'SUCCESS' and len(tf_pos['steps']) >= 2, tf_pos
stages = [s['stage'] for s in tf_pos['steps']]
print(f"[PASS] 5.1 Trace Flow Positive: SUCCESS with {len(tf_pos['steps'])} layer steps: {stages}")

tf_neg = client.post('/projects/10/trace-flow', headers=auth_hdr, json={'question': 'How does purchase order approval work?'}).json()
assert tf_neg['status'] == 'INSUFFICIENT_EVIDENCE' and tf_neg['steps'] == [], tf_neg
print('[PASS] 5.2 Trace Flow Negative: INSUFFICIENT_EVIDENCE (steps=[])')

# 6. Enhancement Impact
enh_pos = client.post('/projects/10/analyze-enhancement', headers=auth_hdr, json={'request': 'Add email notifications to administrators whenever a new missing-person report is submitted.'}).json()
assert enh_pos['status'] == 'SUCCESS', enh_pos
assert enh_pos['complexity'] in ('Low', 'Medium', 'High'), enh_pos
print(f"[PASS] 6.1 Enhancement Positive: SUCCESS, complexity: {enh_pos['complexity']}")

enh_neg = client.post('/projects/10/analyze-enhancement', headers=auth_hdr, json={'request': 'Add purchase-order approval functionality.'}).json()
assert enh_neg['status'] == 'INSUFFICIENT_EVIDENCE' and enh_neg['evidence'] == [], enh_neg
print('[PASS] 6.2 Enhancement Negative: INSUFFICIENT_EVIDENCE (evidence=[])')

# 7. DOCX and PDF Docgen
doc_docx = client.post('/projects/10/generate-doc', headers=auth_hdr, json={'scope': 'full', 'format': 'docx'}).json()
dl_docx = client.get(doc_docx['download_url'], headers=auth_hdr)
assert dl_docx.status_code == 200 and len(dl_docx.content) > 1000
print(f'[PASS] 7.1 Generate & Download DOCX: SUCCESS (size: {len(dl_docx.content)} bytes)')

doc_pdf = client.post('/projects/10/generate-doc', headers=auth_hdr, json={'scope': 'full', 'format': 'pdf'}).json()
dl_pdf = client.get(doc_pdf['download_url'], headers=auth_hdr)
assert dl_pdf.status_code == 200 and len(dl_pdf.content) > 1000
print(f'[PASS] 7.2 Generate & Download PDF: SUCCESS (size: {len(dl_pdf.content)} bytes)')

# 8. Admin Users and Membership
admin_users = client.get('/admin/users', headers=auth_hdr).json()
assert len(admin_users) >= 1 and 'projects' in admin_users[0]
print(f'[PASS] 8. Admin Users: SUCCESS ({len(admin_users)} users with assigned projects)')

print('\n===> ALL 16 ACCEPTANCE CRITERIA PASS 100% ON LIVE CONNECTED REPOSITORY! <===')
