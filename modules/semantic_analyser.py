"""
Semantic Analyser for the Simple C Compiler.

This module is responsible for performing semantic checks on the C-minus code,
ensuring that it adheres to the language's semantic rules beyond just syntactic
correctness. These checks are typically invoked by the parser through specific
semantic action symbols embedded in the grammar productions.

Key responsibilities include:
-   Scope management: Tracking entering and exiting of scopes.
-   Type checking: Verifying type compatibility in assignments, expressions,
    and function calls.
-   Declaration checks: Ensuring identifiers are declared before use, and handling
    the attributes of declarations (type, role, arity, parameters).
-   Control flow checks: Validating the use of 'break' and 'continue' statements.
-   Function call checks: Matching arguments with parameters in terms of number
    and type.
-   Ensuring the presence and correct signature of the 'main' function.

The analyser interacts heavily with the SymbolTableManager to retrieve and
update information about symbols, and uses internal stacks to manage contextual
information needed for various checks. Semantic errors are collected and can be
reported.

Author:             Pasi Pyrrö
Date:               16 March 2020
Modifications:      Added comprehensive docstrings and comments.
"""

import os
from scanner import SymbolTableManager
from code_gen import MemoryManager

script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class SemanticAnalyser(object):
    """
    Performs semantic analysis on the C-minus code.

    This class contains various routines (semantic actions) that are called by the
    parser when specific grammar rules are matched. These routines perform checks
    like type compatibility, scope resolution, declaration verification, etc.

    Attributes:
        semantic_checks (dict): Maps semantic action symbols (e.g., "#SA_INC_SCOPE")
                                to their corresponding handler methods.
        semantic_stacks (dict): A collection of stacks used to store temporary
                                information needed for semantic checks across different
                                parts of a production rule or nested constructs.
        main_found (bool): Flag to track if a 'main' function has been declared.
        main_not_last (bool): Flag to track if 'main' is not the last function,
                              which is a requirement.
        arity_counter (int): Counter, possibly intended for function arity (appears unused).
        while_counter (int): Counter for nested 'while' loops, to validate 'continue'
                             and 'break' statements.
        switch_counter (int): Counter for nested 'switch' statements, to validate 'break'.
        fun_param_list (list): Temporarily stores parameter types during function declaration.
        fun_arg_list (list): Temporarily stores argument types during function call analysis (appears unused).
        _semantic_errors (list): Accumulates semantic errors found, as (line_number, message) tuples.
        semantic_error_file (str): Path to the file where semantic errors will be saved.
    """
    def __init__(self):

        # Maps semantic action symbols (from parser) to their corresponding methods.
        self.semantic_checks = {
            "#SA_INC_SCOPE" : self.inc_scope_routine,
            "#SA_DEC_SCOPE" : self.dec_scope_routine,

            "#SA_SAVE_MAIN" : self.save_main_routine,
            "#SA_MAIN_POP" : self.pop_main_routine,
            "#SA_MAIN_CHECK" : self.check_main_routine,

            "#SA_SAVE_TYPE" : self.save_type_routine,
            "#SA_ASSIGN_TYPE" : self.assign_type_routine,
            "#SA_ASSIGN_FUN_ROLE" : self.assign_fun_role_routine,
            "#SA_ASSIGN_VAR_ROLE" : self.assign_var_role_routine,
            "#SA_ASSIGN_PARAM_ROLE" : self.assign_param_role_routine,
            "#SA_ASSIGN_LENGTH" : self.assign_length_routine,
            "#SA_SAVE_PARAM" : self.save_param_routine,
            "#SA_ASSIGN_FUN_ATTRS" : self.assign_fun_attrs_routine,

            "#SA_CHECK_DECL" : self.check_declaration_routine,

            "#SA_SAVE_FUN" : self.save_fun_routine,
            "#SA_CHECK_ARGS" : self.check_args_routine,

            "#SA_PUSH_ARG_STACK" : self.push_arg_stack_routine,
            "#SA_SAVE_ARG" : self.save_arg_routine,
            "#SA_POP_ARG_STACK" : self.pop_arg_stack_routine, 
            

            "#SA_PUSH_WHILE" : self.push_while_routine,
            "#SA_CHECK_WHILE" : self.check_while_routine,
            "#SA_POP_WHILE" : self.pop_while_routine,

            "#SA_PUSH_SWITCH" : self.push_switch_routine,
            "#SA_CHECK_BREAK" : self.check_break_routine,
            "#SA_POP_SWITCH" : self.pop_switch_routine,

            "#SA_SAVE_TYPE_CHECK" : self.save_type_check_routine,
            "#SA_INDEX_ARRAY" : self.index_array_routine,
            "#SA_INDEX_ARRAY_POP" : self.index_array_pop_routine,
            "#SA_TYPE_CHECK" : self.type_check_routine,
        }

        # Stacks used to hold contextual information during semantic analysis.
        # For example, to pass type information from a type-specifier part of a
        # declaration to the identifier part, or to check operand types in an expression.
        self.semantic_stacks = {
            "main_check" : [],    # Used to collect parts of function signatures to check for 'main'.
            "type_assign" : [],   # Holds types during declaration processing for assignment to symbols.
                                  # Also temporarily holds symbol_idx after type assignment.
            "type_check" : [],    # Stack for types of operands during expression evaluation for type checking.
            "fun_check" : [],     # Holds function ID (index in symbol table) when checking arguments of a call.
        }

        # Flags to track specific semantic conditions.
        self.main_found = False       # True if a 'void main(void)' function is properly declared.
        self.main_not_last = False    # True if 'main' is found but another function is declared after it.

        # Counters for nested structures.
        self.arity_counter = 0        # Appears unused in the current set of routines.
        self.while_counter = 0        # Counts nesting level of 'while' loops for 'break'/'continue' validation.
        self.switch_counter = 0       # Counts nesting level of 'switch' statements for 'break' validation.

        # Lists for collecting information during parsing of specific constructs.
        self.fun_param_list = []      # Stores types of parameters during a function declaration.
        self.fun_arg_list = []        # Intended for storing argument types during function call (currently populated by #SA_SAVE_ARG but not directly used by #SA_CHECK_ARGS, which uses SymbolTableManager.arg_list_stack instead).
        self._semantic_errors = []    # Stores (line_number, error_message) tuples for semantic errors.

        self.semantic_error_file = os.path.join(script_dir, "errors", "semantic_errors.txt")


    @property
    def scope(self):
        """Returns the current scope level from the SymbolTableManager."""
        return len(SymbolTableManager.scope_stack) - 1


    @property
    def semantic_errors(self):
        """
        Formats and returns all recorded semantic errors.

        Returns:
            str: A string containing all semantic errors, formatted for display or logging.
                 Returns "The input program is semantically correct.\n" if no errors were found.
        """
        semantic_errors = []
        if self._semantic_errors:
            for lineno, error in self._semantic_errors:
                semantic_errors.append(f"#{lineno} : Semantic Error! {error}\n")
        else:
            semantic_errors.append("The input program is semantically correct.\n")
        return "".join(semantic_errors)


    def _get_lexim(self, token):
        """
        Helper function to get the lexim (string value) of a token.
        If the token is an ID, it looks up its name in the symbol table.
        Otherwise, it returns the token's value directly (e.g., "int", ";").

        Args:
            token (tuple): The input token (type, value).

        Returns:
            str: The lexim of the token.
        """
        if token[0] == "ID":
            return SymbolTableManager.symbol_table[token[1]]['lexim']
        else:
            return token[1]


    def save_semantic_errors(self):
        """Saves recorded semantic errors to the semantic_error_file."""
        with open(self.semantic_error_file, "w") as f:
            f.write(self.semantic_errors)


    # ------------------------------------------------------------------------------------ #
    # ---                         SEMANTIC ACTION ROUTINES                             --- #
    # ------------------------------------------------------------------------------------ #
    # These methods are called by the parser when corresponding #SA_... symbols are encountered.
    # Each routine performs a specific semantic check or updates semantic state.
    # Parameters:
    #   input_token (tuple): The current token being processed by the parser (type, value).
    #   line_number (int): The current line number in the source file.
    # ------------------------------------------------------------------------------------ #


    def inc_scope_routine(self, input_token, line_number):
        """
        Handles entering a new scope.
        It pushes the current size of the symbol table onto the `scope_stack`
        in `SymbolTableManager`. This marks the point where symbols for the new
        scope begin.
        """
        SymbolTableManager.scope_stack.append(len(SymbolTableManager.symbol_table))


    def dec_scope_routine(self, input_token, line_number):
        """
        Handles exiting the current scope.
        It pops the starting index of the current scope's symbols from
        `SymbolTableManager.scope_stack` and truncates the `symbol_table`
        to this index, effectively removing all symbols declared in the exited scope.
        """
        scope_start_idx = SymbolTableManager.scope_stack.pop()
        SymbolTableManager.symbol_table = SymbolTableManager.symbol_table[:scope_start_idx]


    def save_main_routine(self, input_token, line_number):
        """
        Saves parts of a function's signature (type or ID) onto the `main_check` stack.
        This stack is used by `check_main_routine` to verify if the declared
        function is 'void main(void)'.
        """
        self.semantic_stacks["main_check"].append(self._get_lexim(input_token))


    def pop_main_routine(self, input_token, line_number):
        """
        Pops the last two items from the `main_check` stack.
        This is typically called after a variable declaration part of Declaration-prime,
        to remove the type and ID of a variable that is not a function, keeping the
        stack clean for subsequent function checks or `check_main_routine`.
        """
        self.semantic_stacks["main_check"] = self.semantic_stacks["main_check"][:-2]

    
    def save_type_routine(self, input_token, line_number):
        """
        Saves the type specifier (e.g., "int", "void") encountered during a declaration.
        The type is pushed onto the `type_assign` stack to be later assigned to the
        declared identifier(s). Sets `SymbolTableManager.declaration_flag` to True.
        """
        SymbolTableManager.declaration_flag = True # Signal that a declaration is being processed
        self.semantic_stacks["type_assign"].append(input_token[1]) # Push type string (e.g., "int")


    def assign_type_routine(self, input_token, line_number):
        """
        Assigns the saved type from `type_assign` stack to the current ID token.
        This is called when an ID is encountered in a declaration. The type is popped
        from the stack, assigned to the symbol table entry of the ID, and then the
        ID's symbol_idx is pushed back onto `type_assign` stack for potential role/length assignment.
        Resets `SymbolTableManager.declaration_flag`.
        """
        if input_token[0] == "ID" and self.semantic_stacks["type_assign"]:
            symbol_idx = input_token[1] # ID token's value is its index in symbol table
            # Assign type from stack to the symbol table entry for this ID
            SymbolTableManager.symbol_table[symbol_idx]["type"] = self.semantic_stacks["type_assign"].pop()
            # Push symbol_idx itself for next routines (e.g. assign_fun_role) to know which symbol to update
            self.semantic_stacks["type_assign"].append(symbol_idx)
            SymbolTableManager.declaration_flag = False # End of type part of declaration processing
        

    def assign_fun_role_routine(self, input_token, line_number):
        """
        Assigns the 'function' role to the symbol currently being declared.
        The symbol's index is expected to be on top of the `type_assign` stack.
        Also records the function's starting address in the program block (pb_index).
        """
        if self.semantic_stacks["type_assign"]:
            symbol_idx = self.semantic_stacks["type_assign"][-1] # Get symbol_idx of the function
            SymbolTableManager.symbol_table[symbol_idx]["role"] = "function"
            # Store the starting address of the function's code
            SymbolTableManager.symbol_table[symbol_idx]["address"] = MemoryManager.pb_index

    
    def assign_param_role_routine(self, input_token, line_number):
        """Assigns the 'param' role to a symbol, delegates to `assign_var_role_routine`."""
        self.assign_var_role_routine(input_token, line_number, "param")


    def assign_var_role_routine(self, input_token, line_number, role="local_var"):
        """
        Assigns a role (e.g., 'local_var', 'global_var', 'param') to the symbol being declared.
        The symbol's index is on top of `type_assign` stack.
        Checks for illegal 'void' type for variables/parameters.
        If an array declaration is indicated by `input_token[1] == "["`, sets type to "array".
        """
        if self.semantic_stacks["type_assign"]:
            symbol_idx = self.semantic_stacks["type_assign"][-1] # Get symbol_idx
            symbol_row = SymbolTableManager.symbol_table[symbol_idx]
            symbol_row["role"] = role
            if self.scope == 0: # Global scope
                symbol_row["role"] = "global_var"

            # Check for illegal void type for variables/params
            if symbol_row.get("type") == "void":
                SymbolTableManager.error_flag = True
                self._semantic_errors.append((line_number, "Illegal type of void for '{}'.".format(symbol_row["lexim"])))
                symbol_row.pop("type", None) # Remove invalid type to mark as not properly defined

            # If '[' token follows, it's an array declaration (for non-function declarations)
            if input_token[1] == "[": # input_token here is from Var-declaration-prime
                symbol_row["type"] = "array"


    def assign_length_routine(self, input_token, line_number):
        """
        Assigns array length (arity) or variable size (arity=1 for non-arrays).
        The symbol's index is popped from `type_assign` stack.
        For arrays (NUM token), arity is the number. For simple vars (';' token), arity is 1.
        Allocates memory address/offset from `MemoryManager`.
        If it's an array parameter, updates `fun_param_list` to mark it as "array".
        """
        if self.semantic_stacks["type_assign"]:
            symbol_idx = self.semantic_stacks["type_assign"].pop() # Pop symbol_idx
            symbol_row = SymbolTableManager.symbol_table[symbol_idx]

            if input_token[0] == "NUM": # Array declaration with size
                symbol_row["arity"] = int(input_token[1])
                if symbol_row.get("role") == "param":
                    symbol_row["offset"] = MemoryManager.get_param_offset() # Params get offset in activation record
                else: 
                    symbol_row["address"] = MemoryManager.get_static(int(input_token[1])) # Global/local static vars
            else: # Simple variable or unsized array parameter
                symbol_row["arity"] = 1 # Default arity for non-explicitly-sized arrays/scalars
                if symbol_row.get("role") == "param":
                    symbol_row["offset"] = MemoryManager.get_param_offset()
                else:
                    symbol_row["address"] = MemoryManager.get_static()
                
            # If this is an array parameter being declared, mark its type as 'array' in fun_param_list
            if input_token[1] == "[" and self.fun_param_list and symbol_row.get("role") == "param":
                # This assumes the current param type is the last one added to fun_param_list
                self.fun_param_list[-1] = "array"
            

    def save_param_routine(self, input_token, line_number):
        """
        Saves the type of a function parameter to `self.fun_param_list`.
        `input_token[1]` is expected to be the type string (e.g., "int", "void").
        Note: If it's an array, `assign_length_routine` will update it to "array".
        """
        self.fun_param_list.append(input_token[1]) # input_token is type like 'int' or 'void'

    
    def push_arg_stack_routine(self, input_token, line_number):
        """
        Pushes a new empty list onto `SymbolTableManager.arg_list_stack`.
        This new list will collect the types of arguments for the current function call being parsed.
        """
        SymbolTableManager.arg_list_stack.append([])


    def pop_arg_stack_routine(self, input_token, line_number):
        """
        Pops the topmost list of argument types from `SymbolTableManager.arg_list_stack`.
        This is done after a function call is processed. Ensures stack doesn't underflow.
        """
        if len(SymbolTableManager.arg_list_stack) > 1: # Keep the base empty list
            SymbolTableManager.arg_list_stack.pop()

    
    def save_arg_routine(self, input_token, line_number):
        """
        Saves the type of an argument in a function call.
        The type ("int" for NUM, or looked up type for ID) is appended to the
        current list of arguments at the top of `SymbolTableManager.arg_list_stack`.
        """
        if input_token[0] == "ID":
            # Append type of ID (e.g. "int", "array") or None if not found/defined
            SymbolTableManager.arg_list_stack[-1].append(SymbolTableManager.symbol_table[input_token[1]].get("type"))
        else: # Assumed to be NUM token, so type is "int"
            SymbolTableManager.arg_list_stack[-1].append("int")


    def assign_fun_attrs_routine(self, input_token, line_number):
        """
        Assigns arity (number of parameters) and parameter types to a function symbol.
        The function's symbol index is popped from `type_assign` stack.
        Parameter types are taken from `self.fun_param_list`, which is then cleared.
        Initializes a new temporary variable counter on `SymbolTableManager.temp_stack`.
        """
        if self.semantic_stacks["type_assign"]:
            symbol_idx = self.semantic_stacks["type_assign"].pop() # Pop function's symbol_idx
            params = self.fun_param_list
            SymbolTableManager.symbol_table[symbol_idx]["arity"] = len(params)
            SymbolTableManager.symbol_table[symbol_idx]["params"] = params
            self.fun_param_list = [] # Clear for next function
            SymbolTableManager.temp_stack.append(0) # Initialize temp var counter for this function's scope


    def check_main_routine(self, input_token, line_number):
        """
        Checks if a function just declared matches the 'void main(void)' signature.
        It examines the last three items saved on `main_check` stack (type, name, param_type).
        Updates `self.main_found` and `self.main_not_last` flags.
        This routine is called after a function's compound statement.
        """
        main_signature = ("void", "main", "void") # Expected signature
        try:
            # Get the last three items: return type, function name, first param type (or void if no params)
            top_three = tuple(self.semantic_stacks["main_check"][-3:])
            self.semantic_stacks["main_check"] = self.semantic_stacks["main_check"][:-3] # Consume them

            if not self.main_found:
                # Check if signature matches and it's at global scope (scope 1 just after global)
                self.main_found = (top_three == main_signature and self.scope == 1)
            # Check if main was already found and another function is defined at global scope
            elif not self.main_not_last and self.main_found and self.scope == 1:
                self.main_not_last = True # Error: main is not the last function
        except IndexError:
            # Not enough items on stack for a full function signature check (should not happen with correct grammar)
            pass
    

    def check_declaration_routine(self, input_token, line_number):
        """
        Checks if an identifier used in an expression or statement has been declared.
        An ID is considered declared if its symbol table entry has a 'type' attribute.
        Args:
            input_token (tuple): The ID token (type="ID", value=symbol_table_index).
        """
        # Check if the symbol for the ID has a 'type' field, indicating it's been declared.
        if "type" not in SymbolTableManager.symbol_table[input_token[1]]:
            lexim = self._get_lexim(input_token) # Get the string name of the ID
            SymbolTableManager.error_flag = True
            self._semantic_errors.append((line_number, f"'{lexim}' is not defined."))

    
    def save_fun_routine(self, input_token, line_number):
        """
        Saves a function's ID (symbol table index) onto the `fun_check` stack.
        This is done when a function call is encountered, to later verify its arguments.
        Only saves if the ID indeed refers to a symbol with role 'function'.
        Args:
            input_token (tuple): The ID token of the function being called.
        """
        # Ensure the ID being called is actually a function
        if SymbolTableManager.symbol_table[input_token[1]].get("role") == "function":
            self.semantic_stacks["fun_check"].append(input_token[1]) # Push function's symbol_idx


    def check_args_routine(self, input_token, line_number):
        """
        Checks arguments of a function call against its declared parameters.
        Pops function ID from `fun_check` stack. Gets argument types from
        `SymbolTableManager.arg_list_stack[-1]`. Compares arity and types.
        Clears corresponding entries from `type_check` stack as arguments are expressions.
        """
        if self.semantic_stacks["fun_check"]:
            fun_id = self.semantic_stacks["fun_check"].pop() # Get function's symbol_idx
            fun_entry = SymbolTableManager.symbol_table[fun_id]
            lexim = fun_entry["lexim"]

            # Arguments types were collected on SymbolTableManager.arg_list_stack
            args_types = SymbolTableManager.arg_list_stack[-1] # Current call's argument types

            # Operands of arguments are expressions, their types were pushed on type_check stack.
            # Remove them as they are consumed by the function call.
            if args_types is not None:
                 # This assumes type_check stack has types of args in order.
                self.semantic_stacks["type_check"] = self.semantic_stacks["type_check"][:-(len(args_types))]


            if fun_entry.get("arity") != len(args_types):
                SymbolTableManager.error_flag = True
                self._semantic_errors.append((line_number, f"Mismatch in numbers of arguments of '{lexim}'."))
            else:
                declared_params_types = fun_entry.get("params", [])
                for i, (param_type, arg_type) in enumerate(zip(declared_params_types, args_types)):
                    if param_type != arg_type and arg_type is not None: # arg_type could be None if an arg was undeclared ID
                        SymbolTableManager.error_flag = True
                        self._semantic_errors.append((line_number, f"Mismatch in type of argument {i+1} of '{lexim}'. Expected '{param_type}' but got '{arg_type}' instead."))


    def push_while_routine(self, input_token, line_number):
        """Increments `while_counter` when entering a 'while' loop construct."""
        self.while_counter += 1


    def check_while_routine(self, input_token, line_number):
        """
        Checks if a 'continue' statement is within a 'while' loop.
        Called when 'continue' is encountered. Errors if `while_counter` is zero.
        """
        if self.while_counter <= 0:
            SymbolTableManager.error_flag = True
            self._semantic_errors.append((line_number, f"No 'while' found for 'continue'"))


    def pop_while_routine(self, input_token, line_number):
        """Decrements `while_counter` when exiting a 'while' loop."""
        self.while_counter -= 1

    
    def push_switch_routine(self, input_token, line_number):
        """Increments `switch_counter` when entering a 'switch' statement."""
        self.switch_counter += 1


    def check_break_routine(self, input_token, line_number):
        """
        Checks if a 'break' statement is within a 'while' or 'switch' construct.
        Called when 'break' is encountered. Errors if both counters are zero.
        """
        if self.while_counter <= 0 and self.switch_counter <= 0:
            SymbolTableManager.error_flag = True
            self._semantic_errors.append((line_number, "No 'while' or 'switch' found for 'break'."))


    def pop_switch_routine(self, input_token, line_number):
        """Decrements `switch_counter` when exiting a 'switch' statement."""
        self.switch_counter -= 1


    def save_type_check_routine(self, input_token, line_number):
        """
        Saves the type of an operand onto the `type_check` stack.
        Used for type checking in expressions. If token is ID, its type is fetched
        from symbol table. If NUM, type is "int".
        """
        if input_token[0] == "ID":
            operand_type = SymbolTableManager.symbol_table[input_token[1]].get("type")
        else: # Assumed to be NUM
            operand_type = "int"
        self.semantic_stacks["type_check"].append(operand_type)
    

    def index_array_routine(self, input_token, line_number):
        """
        Handles array indexing. Sets the type of the indexed array element to "int".
        This assumes that an array element access (e.g., `arr[i]`) results in an "int" type value.
        The top of `type_check` stack (which should be "array") is changed to "int".
        """
        if self.semantic_stacks["type_check"]:
            # The type on stack should be 'array' from the ID. After indexing, it's an 'int'.
            # This implicitly checks if the base was an array; if not, type_check will fail later.
            self.semantic_stacks["type_check"][-1] = "int"


    def index_array_pop_routine(self, input_token, line_number):
        """
        Pops a type from `type_check` stack after array indexing is fully processed.
        This is used when array indexing is part of an expression that doesn't
        immediately lead to a binary operation (e.g., in a function call argument `arr[i]`).
        The result of `arr[i]` (an "int") was already on stack; this might be cleaning up
        an intermediate type related to the index expression itself if it was pushed.
        However, typical usage suggests this cleans up the type of the *array index expression*,
        which should have been type-checked to be 'int'.
        """
        if self.semantic_stacks["type_check"]:
            # This typically pops the type of the expression *inside* the brackets `[Expression]`.
            # That expression should have resulted in an 'int'.
            self.semantic_stacks["type_check"].pop()


    def type_check_routine(self, input_token, line_number):
        """
        Performs type checking for binary operations or assignments.
        Pops two operand types from `type_check` stack. Checks for compatibility:
        - Array types cannot be operands directly in arithmetic/comparison (should be indexed).
        - Types must match for the operation.
        If types are compatible, pushes the result type back (usually same as operands for C-minus).
        """
        try:
            operand_b_type = self.semantic_stacks["type_check"].pop()
            operand_a_type = self.semantic_stacks["type_check"].pop()

            if operand_b_type is not None and operand_a_type is not None: # Both types must be known
                if operand_a_type == "array": # Left operand cannot be an un-indexed array
                    SymbolTableManager.error_flag = True
                    self._semantic_errors.append((line_number, 
                        f"Type mismatch in operands, Got '{operand_a_type}' instead of 'int'."))
                elif operand_a_type != operand_b_type: # Types must match
                    SymbolTableManager.error_flag = True
                    self._semantic_errors.append((line_number, 
                        f"Type mismatch in operands, Got '{operand_b_type}' instead of '{operand_a_type}'."))
                else:
                    # If checks pass, push the resulting type (which is same as operands for these ops)
                    self.semantic_stacks["type_check"].append(operand_a_type)
            # If one of the types was None (e.g. from undeclared var), an error was already reported.
            # No need to push anything back as the operation is invalid.
        except IndexError:
            # Not enough operands on stack for a binary operation.
            # This indicates a prior error or grammar issue.
            # SymbolTableManager.error_flag = True # Already true if types were missing
            # self._semantic_errors.append((line_number, "Insufficient operands for type check."))
            pass


    # ---                         END OF SEMANTIC ROUTINES                             --- #


    def semantic_check(self, action_symbol, input_token, line_number):
        """
        Dispatcher for semantic actions.
        Calls the appropriate routine based on the `action_symbol`.

        Args:
            action_symbol (str): The semantic action symbol from the parser (e.g., "#SA_INC_SCOPE").
            input_token (tuple): The current token from the parser.
            line_number (int): The current line number.
        """
        try:
            self.semantic_checks[action_symbol](input_token, line_number)
        except Exception as e:
            # General error catching for unexpected issues within a semantic routine.
            print(f"{line_number} : Error in semantic routine {action_symbol}:", str(e))


    def eof_check(self, line_number):
        """
        Performs end-of-file semantic checks.
        Currently, verifies that a 'main' function was found and was the last function defined.
        Args:
            line_number (int): The line number at EOF (or end of parsing).
        """
        if not self.main_found or self.main_not_last:
            SymbolTableManager.error_flag = True
            self._semantic_errors.append((line_number, "main function not found!"))
