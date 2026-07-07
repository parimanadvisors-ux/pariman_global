import os
import json
from app import create_app, db
from models import User, Role, UserRole
from sqlalchemy import text
from werkzeug.security import generate_password_hash

app = create_app()

def merge_staff():
    with app.app_context():
        # 1. Fetch legacy ITR users from Postgres
        itr_users = []
        try:
            result = db.session.execute(text("SELECT value FROM itr.kv_store WHERE key = 'users'")).fetchone()
            if result and result[0]:
                # value is stored as JSONB, which SQLAlchemy returns as a Python list/dict
                itr_users = result[0] if isinstance(result[0], list) else json.loads(result[0])
        except Exception as e:
            print(f"Note: No legacy ITR users found or table empty: {e}")

        # 2. Fetch legacy Policy users from Postgres
        policy_users = []
        try:
            rows = db.session.execute(text("SELECT data FROM policy.records WHERE store = 'users'")).fetchall()
            policy_users = [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]
        except Exception as e:
            print(f"Note: No legacy Policy users found or table empty: {e}")

        print(f"Scanning data: Found {len(itr_users)} ITR legacy records and {len(policy_users)} Policy legacy records.")

        # Dictionary to hold the unified, deduplicated staff profiles
        merged_profiles = {}

        # Process ITR legacy users
        for u in itr_users:
            email = u.get('email') or u.get('username')
            if not email:
                continue
            if '@' not in email:
                email = f"{email}@parimanglobal.com"
            
            email = email.lower().strip()
            merged_profiles[email] = {
                'username': u.get('username', email.split('@')[0]),
                'password': u.get('password', 'pariman123'), # Fallback if missing
                'name': u.get('name', email.split('@')[0].title()),
                'role': 'SuperAdmin' if u.get('role') == 'admin' else 'Staff',
                'designation': 'Administrator' if u.get('role') == 'admin' else 'Staff Member',
                'mobile': u.get('mobile', '')
            }

        # Process Policy legacy users and merge/supplement
        for u in policy_users:
            email = u.get('email') or u.get('username')
            if not email:
                continue
            if '@' not in email:
                email = f"{email}@parimanglobal.com"
            
            email = email.lower().strip()
            
            if email not in merged_profiles:
                merged_profiles[email] = {
                    'username': u.get('username', email.split('@')[0]),
                    'password': u.get('password', 'pariman123'),
                    'name': u.get('name', email.split('@')[0].title()),
                    'role': 'SuperAdmin' if u.get('role') == 'admin' else 'Staff',
                    'designation': u.get('designation', 'Staff Member'),
                    'mobile': u.get('mobile', '')
                }
            else:
                # Supplement details if they exist in POPMS but were missing in ITR
                p = merged_profiles[email]
                if u.get('designation') and p['designation'] == 'Staff Member':
                    p['designation'] = u.get('designation')
                if u.get('mobile') and not p['mobile']:
                    p['mobile'] = u.get('mobile')

        # 3. Insert and reconcile into core.users
        super_admin_role = Role.query.filter_by(name='SuperAdmin').first()
        staff_role = Role.query.filter_by(name='Staff').first()

        success_count = 0
        for email, p in merged_profiles.items():
            # Skip or supplement the root SuperAdmin we already seeded to prevent duplicate key crashes
            if email == os.environ.get('ROOT_ADMIN_USER', 'admin@parimanglobal.com'):
                root_user = User.query.filter_by(email=email).first()
                if root_user:
                    root_user.name = p['name']
                    root_user.designation = p['designation']
                    root_user.mobile = p['mobile']
                    db.session.commit()
                continue

            existing_user = User.query.filter_by(email=email).first()
            if not existing_user:
                print(f"Reconciling: Creating central SSO account for: {email}")
                hashed_pw = generate_password_hash(p['password'])
                new_user = User(
                    email=email,
                    password_hash=hashed_pw,
                    is_active=True,
                    name=p['name'],
                    designation=p['designation'],
                    mobile=p['mobile']
                )
                db.session.add(new_user)
                db.session.flush()

                # Assign Role
                chosen_role = super_admin_role if p['role'] == 'SuperAdmin' else staff_role
                user_role = UserRole(user_id=new_user.id, role_id=chosen_role.id)
                db.session.add(user_role)
                db.session.commit()
                success_count += 1
            else:
                # Just supplement profile details of already created users
                existing_user.name = p['name']
                existing_user.designation = p['designation']
                existing_user.mobile = p['mobile']
                db.session.commit()

        print(f"Reconciliation successful! Imported and secured {success_count} legacy staff members into core.users.")

if __name__ == '__main__':
    merge_staff()
