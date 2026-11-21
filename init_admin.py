import os
from werkzeug.security import generate_password_hash
from db import get_connection

username = os.getenv("admin_user", "admin")
password = os.getenv("admin_pass", "admin@123")
full_name = os.getenv("admin_name", "Alex")

def main():
  con = get_connection() 

  try:
    with con.cursor() as cor:
      cor.execute("select admin_id from admin where username = %s", (username, )) 
      if cor.fetchone():
        print(f"admin '{username}' already exists! ")
        return
      
      cor.execute(
        "insert into admin (username, password_hash, full_name, role)"
        "values (%s, %s, %s, %s)",
        (username, generate_password_hash(password), full_name, "librarian"), 
      )
    con.commit()
    print(f"Created admin '{username}' with '{password}' password!")

  finally: 
    con.close()

if __name__ == "__main__":
  main()