BACKEND_TO_FRONTEND_ROLE = {
    "admin": "school_admin",
    "school_admin": "school_admin",
    "teacher": "teacher",
    "student": "student",
    "guardian": "guardian",
    "accountant": "accountant",
}

def get_frontend_role(user):
   if user.is_superuser:
       return "super_admin"
   
   return BACKEND_TO_FRONTEND_ROLE.get(user.role, user.role)