import sys
import os
# Bind architect root
sys.path.append(os.path.join(os.getcwd(), 'SyntyCode'))

from sdk import (
    GraphContext, Node, Variable, Call, Condition, Function,
    Import, ClassNode, Loop, TryCatch, Identifier
)

if __name__ == "__main__":
    with GraphContext("AuthModule") as ctx:
        # Import crypto lib
        crypto_import = Import("crypto_lib", ["verify_hash", "generate_salt"])
        ctx.add_node(crypto_import)
        
        # BaseAuth Class
        base_auth = ClassNode("BaseAuth")
        
        base_init = Function("__init__", ["self"])
        base_init.add_statement(Variable("self.is_authenticated", raw_value=False, value_type="boolean"))
        base_auth.add_method(base_init)
        
        ctx.add_node(base_auth)
        
        # OAuth Class inheriting BaseAuth
        oauth = ClassNode("OAuth", inherits="BaseAuth")
        
        oauth_init = Function("__init__", ["self", "provider"])
        oauth_init.add_statement(Call("super().__init__", []))
        oauth_init.add_statement(Variable("self.provider", Identifier("provider")))
        oauth.add_method(oauth_init)
        
        # Method with loop and try-catch and complex variable
        auth_func = Function("authenticate", ["self", "credentials"])
        
        # Complex variable: dict
        creds_var = Variable("provider_configs", raw_value={"google": "oauth2", "github": "oauth1"}, value_type="dict")
        auth_func.add_statement(creds_var)
        
        # Loop over credentials
        loop = Loop("for", "cred in credentials")
        
        # Try-Catch
        tc = TryCatch(exception_type="Exception", exception_var="e")
        
        # Inside Try
        is_valid = Variable("is_valid", Call("verify_hash", ["cred.password", "cred.hash"]))
        tc.try_block.add_statement(is_valid)
        
        cond = Condition(
            check=Identifier("is_valid"),
            on_true=Call("self.grant_access", ["cred.user_id"]),
            on_false=Call("self.reject_access", ["cred.user_id"])
        )
        tc.try_block.add_statement(cond)
        
        # Inside Catch
        tc.catch_block.add_statement(Call("print", ["f'Auth failed: {e}'"]))
        
        loop.add_statement(tc)
        auth_func.add_statement(loop)
        
        oauth.add_method(auth_func)
        ctx.add_node(oauth)
