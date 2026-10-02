import sys
sys.path.append('.')
from sdk import GraphContext, Function, Variable, Call, Condition

# Modify AuthModule to return something completely different
with GraphContext("AuthModule") as ctx:
    login_func = Function("authenticate_user", inputs=["user_id", "password"])
    
    # We declare a variable 'is_valid' that calls 'crypto_verify'
    is_valid_check = Variable("is_valid", Call("crypto_verify", args=["password"]))
    login_func.add_statement(is_valid_check)
    
    # ADD ANOTHER STATEMENT
    login_func.add_statement(Call("print", args=["'New Statement'"]))
    
    ctx.add_function(login_func)
