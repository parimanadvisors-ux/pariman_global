import os
from app import create_app, db
from models import User, Role, UserRole

app = create_app()

def seed_admin():
    with app.app_context():
        # 1. Ensure core roles exist
        default_roles = ['SuperAdmin', 'Staff', 'Client']
        for role_name in default_roles:
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                new_role = Role(name=role_name, description=f"{role_name} Role")
                db.session.add(new_role)
        db.session.commit()

        # 2. Check for Root Admin credentials in environment
        root_email = os.environ.get('ROOT_ADMIN_USER')
        root_hash = os.environ.get('ROOT_ADMIN_PASS_HASH')

        if not root_email or not root_hash or root_hash == 'placeholder_hash':
            print("Skipping admin creation: Valid ROOT_ADMIN_USER or ROOT_ADMIN_PASS_HASH missing in .env")
            return

        # 3. Seed Root Admin if it doesn't exist
        admin_user = User.query.filter_by(email=root_email).first()
        if not admin_user:
            print(f"Creating root admin: {root_email}")
            admin_user = User(email=root_email, password_hash=root_hash, is_active=True)
            db.session.add(admin_user)
            db.session.commit()
            
            # Assign SuperAdmin role
            super_admin_role = Role.query.filter_by(name='SuperAdmin').first()
            user_role = UserRole(user_id=admin_user.id, role_id=super_admin_role.id)
            db.session.add(user_role)
            db.session.commit()
            print("Root admin and roles seeded successfully.")
        else:
            print("Root admin already exists. No action taken.")

if __name__ == '__main__':
    seed_admin()