import sys
sys.path.append('.')
from sdk import GraphContext, Function, Variable, Call, Condition

with GraphContext("AuthModule") as ctx:
    login_func = Function("authenticate_user", inputs=["user_id", "password"])
    
    is_valid_check = Variable("is_valid", Call("crypto_verify", args=["password"]))
    login_func.add_statement(is_valid_check)
    
    login_func.add_statement(
        Condition(
            check=Call("is_true", args=["is_valid"]),
            on_true=Call("grant_access", args=["user_id"]),
            on_false=Call("reject_access", args=[])
        )
    )
    
    login_func.add_statement(Call("print", args=["'done'"]))
    
    ctx.add_function(login_func)
