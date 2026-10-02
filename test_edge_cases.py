import sys
sys.path.append('.')
from sdk import GraphContext, Function, Variable, Call, Condition

with GraphContext("DeepModule") as ctx:
    func = Function("deep_nesting", inputs=["a", "b"])
    
    # if a > b:
    #     if a > 10:
    #         print("a is big")
    #     else:
    #         print("a is small")
    # else:
    #     print("b is bigger")
    
    func.add_statement(
        Condition(
            check=Call("greater_than", args=["a", "b"]),
            on_true=Condition(
                check=Call("greater_than", args=["a", "10"]),
                on_true=Call("print", args=["'a is big'"]),
                on_false=Call("print", args=["'a is small'"])
            ),
            on_false=Call("print", args=["'b is bigger'"])
        )
    )
    
    ctx.add_function(func)
