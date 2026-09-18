import sqlite3

con = sqlite3.connect("codesense.db")
con.execute("UPDATE users SET role = 'admin' WHERE id = 1")
con.commit()
cur = con.execute("SELECT id, email, role FROM users WHERE id = 1")
print("User updated:", cur.fetchone())
con.close()
