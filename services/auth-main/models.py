from datetime import datetime, timezone
from app import db

class Role(db.Model):
    __tablename__ = 'roles'
    __table_args__ = {'schema': 'core'}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))

class Permission(db.Model):
    __tablename__ = 'permissions'
    __table_args__ = {'schema': 'core'}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))

class RolePermission(db.Model):
    __tablename__ = 'role_permissions'
    __table_args__ = {'schema': 'core'}
    
    role_id = db.Column(db.Integer, db.ForeignKey('core.roles.id'), primary_key=True)
    permission_id = db.Column(db.Integer, db.ForeignKey('core.permissions.id'), primary_key=True)

class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'core'}
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class UserRole(db.Model):
    __tablename__ = 'user_roles'
    __table_args__ = {'schema': 'core'}
    
    user_id = db.Column(db.Integer, db.ForeignKey('core.users.id'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('core.roles.id'), primary_key=True)

class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    __table_args__ = {'schema': 'core'}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False) # The real user making the change
    impersonated_user_id = db.Column(db.Integer, nullable=True) # Populated if admin is acting as staff
    action = db.Column(db.String(100), nullable=False) # e.g., UPDATE_USER, COMMIT_TAX_RECORD
    target_table = db.Column(db.String(100), nullable=False)
    target_id = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.JSON, nullable=True) # JSON is permitted here strictly for diffing historical states
    new_value = db.Column(db.JSON, nullable=True)
    source_ip = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))