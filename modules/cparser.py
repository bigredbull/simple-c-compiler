"""
Syntax Analyzer (Parser) for the Simple C Compiler.

This module implements a table-driven predictive parser (LL(1)) for the C-minus
language. It takes a stream of tokens from the Scanner and verifies if the
sequence conforms to the C-minus grammar rules.

Key responsibilities:
-   Constructing a parse tree representing the syntactic structure of the input code.
-   Reporting syntax errors.
-   Invoking semantic analysis routines and code generation routines via
    special action symbols embedded within the grammar productions.

The parsing process is guided by a pre-defined parsing table and a set of
production rules.

Author:             Pasi Pyrrö
Date:               20 March 2020
Modifications:      Added comprehensive docstrings and comments.
"""

import os
from anytree import Node, RenderTree, PreOrderIter
from scanner import Scanner, SymbolTableManager
from semantic_analyser import SemanticAnalyser
from code_gen import CodeGen, MemoryManager

script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Maps non-terminal symbols to a string representing a minimal,
# syntactically plausible code snippet for that non-terminal.
# This is used in syntax error messages when a "SYNCH" entry is encountered
# in the parsing table, suggesting to the user what kind of construct was expected.
non_terminal_to_missing_construct = {
    "Program"                       : "int ID;",  # e.g., expected a program structure
    "Declaration-list"              : "int ID;",  # e.g., expected a declaration
    "Declaration"                   : "int ID;",
    "Declaration-initial"           : "int ID",
    "Declaration-prime"             : ";",
    "Var-declaration-prime"         : ";",
    "Fun-declaration-prime"         : "(void) {int ID;}",
    "Type-specifier"                : "int",
    "Params"                        : "void",
    "Param-list-void-abtar"         : "ID",
    "Param-list"                    : ", int ID",
    "Param"                         : "int ID",
    "Param-prime"                   : "[]",
    "Compound-stmt"                 : "{int ID;}",
    "Statement-list"                : ";",
    "Statement"                     : ";",
    "Expression-stmt"               : ";",
    "Selection-stmt"                : "if (NUM); else;",
    "Iteration-stmt"                : "while (NUM);",
    "Return-stmt"                   : "return;",
    "Return-stmt-prime"             : ";",
    "Switch-stmt"                   : "switch (NUM) {}",
    "Case-stmts"                    : "case NUM",
    "Case-stmt"                     : "case NUM",
    "Default-stmt"                  : "default: ;",
    "Expression"                    : "NUM",
    "B"                             : "NUM",
    "H"                             : "NUM",
    "Simple-expression-zegond"      : "NUM",
    "Simple-expression-prime"       : "()",
    "C"                             : "< NUM",
    "Relop"                         : "<",
    "Additive-expression"           : "NUM",
    "Additive-expression-prime"     : "()",
    "Additive-expression-zegond"    : "NUM",
    "D"                             : "+ NUM",
    "Addop"                         : "+",
    "Term"                          : "NUM",
    "Term-prime"                    : "()",
    "Term-zegond"                   : "NUM",
    "G"                             : "* NUM",
    "Factor"                        : "NUM",
    "Var-call-prime"                : "()",
    "Var-prime"                     : "[NUM]",
    "Factor-prime"                  : "()",
    "Factor-zegond"                 : "NUM",
    "Args"                          : "NUM",
    "Arg-list"                      : "NUM",
    "Arg-list-prime"                : ", NUM",    # e.g., expected another argument
}

# Defines the grammar production rules.
# Each string is a right-hand side (RHS) of a production rule.
# The index of the string in this tuple corresponds to the production rule number
# used in the parsing_table.
# - "EPSILON" represents an empty production (derives nothing).
# - Symbols starting with "#SA_" are semantic action hooks for the SemanticAnalyser.
# - Symbols starting with "#CG_" are code generation hooks for the CodeGen.
# - "SYNCH" is a special marker for synchronization points during error recovery.
# - "EMPTY" might indicate an explicit error entry in the grammar or table.
productions = (
    "",                                                                 # 0: Placeholder or unused
    "Declaration-list",                                                 # 1: Program -> Declaration-list
    "Declaration Declaration-list",                                     # 2: Declaration-list -> Declaration Declaration-list
    "EPSILON",                                                          # 3: Declaration-list -> EPSILON
    "Declaration-initial Declaration-prime",                            # 4: Declaration -> Declaration-initial Declaration-prime
    "#SA_SAVE_MAIN #SA_SAVE_TYPE Type-specifier #SA_SAVE_MAIN #SA_ASSIGN_TYPE ID", # 5: Declaration-initial -> ... ID
    "#SA_ASSIGN_FUN_ROLE Fun-declaration-prime",                        # 6: Declaration-prime -> Fun-declaration-prime (function)
    "#SA_ASSIGN_VAR_ROLE #SA_MAIN_POP Var-declaration-prime",           # 7: Declaration-prime -> Var-declaration-prime (variable)
    "#SA_ASSIGN_LENGTH ;",                                              # 8: Var-declaration-prime -> ; (simple variable)
    "[ #SA_ASSIGN_LENGTH NUM ] ;",                                      # 9: Var-declaration-prime -> [ NUM ] ; (array)
    "( #SA_INC_SCOPE #SA_SAVE_MAIN Params #SA_ASSIGN_FUN_ATTRS ) #SA_MAIN_CHECK Compound-stmt #CG_CALC_STACKFRAME_SIZE #CG_RETURN_SEQ_CALLEE #SA_DEC_SCOPE", # 10: Fun-declaration-prime -> ( Params ) Compound-stmt
    "int",                                                              # 11: Type-specifier -> int
    "void",                                                             # 12: Type-specifier -> void
    "#SA_SAVE_TYPE #SA_SAVE_PARAM int #SA_ASSIGN_TYPE ID #SA_ASSIGN_PARAM_ROLE Param-prime Param-list", # 13: Params -> int ID Param-prime Param-list
    "void Param-list-void-abtar",                                       # 14: Params -> void Param-list-void-abtar
    "ID Param-prime Param-list",                                        # 15: Param-list-void-abtar -> ID Param-prime Param-list (if params starts with ID after void)
    "EPSILON",                                                          # 16: Param-list-void-abtar -> EPSILON (if just "void")
    ", #SA_SAVE_PARAM Param Param-list",                                # 17: Param-list -> , Param Param-list
    "EPSILON",                                                          # 18: Param-list -> EPSILON
    "Declaration-initial #SA_ASSIGN_PARAM_ROLE Param-prime",            # 19: Param -> Declaration-initial Param-prime
    "#SA_ASSIGN_LENGTH [ ]",                                            # 20: Param-prime -> [ ] (array parameter)
    "#SA_ASSIGN_LENGTH EPSILON",                                        # 21: Param-prime -> EPSILON (simple parameter)
    "{ Declaration-list Statement-list }",                              # 22: Compound-stmt -> { Declaration-list Statement-list }
    "Statement Statement-list",                                         # 23: Statement-list -> Statement Statement-list
    "EPSILON",                                                          # 24: Statement-list -> EPSILON
    "Expression-stmt",                                                  # 25: Statement -> Expression-stmt
    "Compound-stmt",                                                    # 26: Statement -> Compound-stmt
    "Selection-stmt",                                                   # 27: Statement -> Selection-stmt
    "Iteration-stmt",                                                   # 28: Statement -> Iteration-stmt
    "Return-stmt",                                                      # 29: Statement -> Return-stmt
    "Switch-stmt",                                                      # 30: Statement -> Switch-stmt
    "Expression #CG_CLOSE_STMT ;",                                      # 31: Expression-stmt -> Expression ; | ; (if expr is EPSILON)
    "#SA_CHECK_WHILE #CG_CONT_JP continue ;",                           # 32: Expression-stmt -> continue ;
    "#SA_CHECK_BREAK #CG_BREAK_JP_SAVE break ;",                        # 33: Expression-stmt -> break ;
    ";",                                                                # 34: Expression-stmt -> ; (empty statement)
    "if ( Expression ) #CG_SAVE Statement else #CG_ELSE Statement #CG_IF_ELSE", # 35: Selection-stmt -> if ( Expression ) Statement else Statement
    "#SA_PUSH_WHILE while #CG_LABEL #CG_INIT_WHILE_STACKS ( Expression ) #CG_SAVE Statement #CG_WHILE #SA_POP_WHILE", # 36: Iteration-stmt -> while ( Expression ) Statement
    "return Return-stmt-prime #CG_SET_RETVAL #CG_RETURN_SEQ_CALLEE",     # 37: Return-stmt -> return Return-stmt-prime
    ";",                                                                # 38: Return-stmt-prime -> ; (return without value)
    "Expression ;",                                                     # 39: Return-stmt-prime -> Expression ; (return with value)
    "#SA_PUSH_SWITCH switch ( Expression ) { Case-stmts Default-stmt } #SA_POP_SWITCH", # 40: Switch-stmt -> switch ( Expression ) { Case-stmts Default-stmt }
    "Case-stmt Case-stmts",                                             # 41: Case-stmts -> Case-stmt Case-stmts
    "EPSILON",                                                          # 42: Case-stmts -> EPSILON
    "case NUM : Statement-list",                                        # 43: Case-stmt -> case NUM : Statement-list
    "default : Statement-list",                                         # 44: Default-stmt -> default : Statement-list
    "EPSILON",                                                          # 45: Default-stmt -> EPSILON (no default case)
    "Simple-expression-zegond",                                         # 46: Expression -> Simple-expression-zegond (for (NUM) or (ID(...)))
    "#SA_CHECK_DECL #SA_SAVE_FUN #SA_SAVE_TYPE_CHECK #CG_PUSH_ID ID B", # 47: Expression -> ID B (variable or function call or assignment)
    "= Expression #SA_TYPE_CHECK #CG_ASSIGN",                           # 48: B -> = Expression (assignment)
    "#SA_INDEX_ARRAY [ Expression ] #SA_INDEX_ARRAY_POP H",             # 49: B -> [ Expression ] H (array access)
    "Simple-expression-prime",                                          # 50: B -> Simple-expression-prime (if B is part of a simple expression, not assignment/array)
                                                                        # This means H can also be Simple-expression-prime
    "= Expression #SA_TYPE_CHECK #CG_ASSIGN",                           # 51: H -> = Expression (assignment after array indexing)
    "G D C",                                                            # 52: H -> G D C (part of arithmetic/relational expr after array indexing)
    "Additive-expression-zegond C",                                     # 53: Simple-expression-zegond -> Additive-expression-zegond C
    "Additive-expression-prime C",                                      # 54: Simple-expression-prime -> Additive-expression-prime C (used when it's not an assignment)
    "#CG_SAVE_OP Relop Additive-expression #SA_TYPE_CHECK #CG_RELOP",   # 55: C -> Relop Additive-expression
    "EPSILON",                                                          # 56: C -> EPSILON
    "<",                                                                # 57: Relop -> <
    "==",                                                               # 58: Relop -> ==
    "Term D",                                                           # 59: Additive-expression -> Term D (Old: Additive-expression-zegond)
    "Term-prime D",                                                     # 60: Additive-expression-prime -> Term-prime D
    "Term-zegond D",                                                    # 61: Additive-expression-zegond -> Term-zegond D
    "#CG_SAVE_OP Addop Term #SA_TYPE_CHECK #CG_ADDOP D",                # 62: D -> Addop Term D
    "EPSILON",                                                          # 63: D -> EPSILON
    "+",                                                                # 64: Addop -> +
    "-",                                                                # 65: Addop -> -
    "Factor G",                                                         # 66: Term -> Factor G (Old: Term-zegond)
    "Factor-prime G",                                                   # 67: Term-prime -> Factor-prime G
    "Factor-zegond G",                                                  # 68: Term-zegond -> Factor-zegond G
    "* Factor #SA_TYPE_CHECK #CG_MULT G",                               # 69: G -> * Factor G
    "EPSILON",                                                          # 70: G -> EPSILON
    "( Expression )",                                                   # 71: Factor -> ( Expression )
    "#SA_CHECK_DECL #SA_SAVE_FUN #SA_SAVE_TYPE_CHECK #CG_PUSH_ID ID Var-call-prime", # 72: Factor -> ID Var-call-prime (variable or function call)
    "#SA_SAVE_TYPE_CHECK #CG_PUSH_CONST NUM",                           # 73: Factor -> NUM
    "#SA_PUSH_ARG_STACK ( Args #SA_CHECK_ARGS ) #CG_CALL_SEQ_CALLER #SA_POP_ARG_STACK", # 74: Var-call-prime -> ( Args ) (function call)
    "Var-prime",                                                        # 75: Var-call-prime -> Var-prime (variable access, possibly array)
    "#SA_INDEX_ARRAY [ Expression ] #SA_INDEX_ARRAY_POP",               # 76: Var-prime -> [ Expression ] (array element access)
    "EPSILON",                                                          # 77: Var-prime -> EPSILON (simple variable)
    "#SA_PUSH_ARG_STACK ( Args #SA_CHECK_ARGS ) #CG_CALL_SEQ_CALLER #SA_POP_ARG_STACK", # 78: Factor-prime -> ( Args ) (function call, factor context)
    "EPSILON",                                                          # 79: Factor-prime -> EPSILON (if Factor is just ID or NUM, not a call)
    "( Expression )",                                                   # 80: Factor-zegond -> ( Expression )
    "#SA_SAVE_TYPE_CHECK #CG_PUSH_CONST NUM",                           # 81: Factor-zegond -> NUM
    "Arg-list",                                                         # 82: Args -> Arg-list
    "EPSILON",                                                          # 83: Args -> EPSILON (no arguments)
    "#SA_SAVE_ARG Expression Arg-list-prime",                           # 84: Arg-list -> Expression Arg-list-prime
    ", #SA_SAVE_ARG Expression Arg-list-prime",                         # 85: Arg-list-prime -> , Expression Arg-list-prime
    "EPSILON",                                                          # 86: Arg-list-prime -> EPSILON
    "SYNCH",                                                            # 87: Special rule for error recovery (synchronize)
    "EMPTY"                                                             # 88: Special rule for error state (panic mode, skip token)
)

# Convert string productions to lists of symbols for easier processing.
productions = tuple([p.split() for p in productions])

# Maps terminal symbols (token types from scanner) to column indices in the parsing_table.
terminal_to_col = {
    "ID"        : 0,  # Identifier
    ";"         : 1,  # Semicolon
    "["         : 2,  # Left square bracket
    "NUM"       : 3,  # Number
    "]"         : 4,  # Right square bracket
    "("         : 5,  # Left parenthesis
    ")"         : 6,  # Right parenthesis
    "int"       : 7,  # Keyword "int"
    "void"      : 8,  # Keyword "void"
    ","         : 9,  # Comma
    "{"         : 10, # Left curly brace
    "}"         : 11, # Right curly brace
    "continue"  : 12, # Keyword "continue"
    "break"     : 13, # Keyword "break"
    "if"        : 14, # Keyword "if"
    "else"      : 15, # Keyword "else"
    "while"     : 16, # Keyword "while"
    "return"    : 17, # Keyword "return"
    "switch"    : 18, # Keyword "switch"
    "case"      : 19, # Keyword "case"
    ":"         : 20, # Colon
    "default"   : 21, # Keyword "default"
    "="         : 22, # Assignment operator
    "<"         : 23, # Less than operator
    "=="        : 24, # Equality operator
    "+"         : 25, # Plus operator
    "-"         : 26, # Minus operator
    "*"         : 27, # Asterisk (multiplication)
    "$"         : 28  # End-of-input marker
}

# Maps non-terminal symbols (grammar variables) to row indices in the parsing_table.
non_terminal_to_row = {
    "Program"                       : 0,  # Start symbol of the grammar
    "Declaration-list"              : 1,
    "Declaration"                   : 2,
    "Declaration-initial"           : 3,
    "Declaration-prime"             : 4,
    "Var-declaration-prime"         : 5,
    "Fun-declaration-prime"         : 6,
    "Type-specifier"                : 7,
    "Params"                        : 8,
    "Param-list-void-abtar"         : 9,
    "Param-list"                    : 10,
    "Param"                         : 11,
    "Param-prime"                   : 12,
    "Compound-stmt"                 : 13,
    "Statement-list"                : 14,
    "Statement"                     : 15,
    "Expression-stmt"               : 16,
    "Selection-stmt"                : 17,
    "Iteration-stmt"                : 18,
    "Return-stmt"                   : 19,
    "Return-stmt-prime"             : 20,
    "Switch-stmt"                   : 21,
    "Case-stmts"                    : 22,
    "Case-stmt"                     : 23,
    "Default-stmt"                  : 24,
    "Expression"                    : 25,
    "B"                             : 26,
    "H"                             : 27,
    "Simple-expression-zegond"      : 28,
    "Simple-expression-prime"       : 29,
    "C"                             : 30,
    "Relop"                         : 31,
    "Additive-expression"           : 32,
    "Additive-expression-prime"     : 33,
    "Additive-expression-zegond"    : 34,
    "D"                             : 35,
    "Addop"                         : 36,
    "Term"                          : 37,
    "Term-prime"                    : 38,
    "Term-zegond"                   : 39,
    "G"                             : 40,
    "Factor"                        : 41,
    "Var-call-prime"                : 42,
    "Var-prime"                     : 43,
    "Factor-prime"                  : 44,
    "Factor-zegond"                 : 45,
    "Args"                          : 46,
    "Arg-list"                      : 47,
    "Arg-list-prime"                : 48
}

# The LL(1) parsing table.
# `parsing_table[row_index][column_index]` gives the production rule number (index in `productions`)
# to be used when the non-terminal corresponding to `row_index` (from `non_terminal_to_row`)
# is on top of the parsing stack, and the current input token's type corresponds to
# `column_index` (from `terminal_to_col`).
#
# Example: `parsing_table[non_terminal_to_row["Program"]][terminal_to_col["int"]]` would
# give the production rule for "Program" when the lookahead token is "int".
# The values 87 and 88 correspond to productions "SYNCH" and "EMPTY" respectively,
# used for error handling.
parsing_table = (
    # Columns are terminals as per terminal_to_col:
    #ID(0);(1) [(2)NUM(3)](4) ((5))(6)int(7)void(8),(9) {(10)}(11)cont(12)brk(13)if(14)else(15)whl(16)ret(17)sw(18)case(19):(20)def(21)=(22)<(23)==(24)+(25)-(26)*(27) $(28)
    (88,  88,  88,  88,  88,  88,  88,   1,   1,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 0: Program
    ( 3,   3,  88,   3,  88,   3,  88,   2,   2,  88,   3,   3,   3,   3,   3,  88,   3,   3,   3,  88,  88,  88,  88,  88,  88,  88,  88,  88,   3), # Row 1: Declaration-list
    (87,  87,  88,  87,  88,  87,  88,   4,   4,  88,  87,  88,  87,  87,  87,  88,  87,  87,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 2: Declaration
    (88,  87,  87,  88,  88,  87,  87,   5,   5,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 3: Declaration-initial
    (87,   7,   7,  87,  88,   6,  88,  87,  87,  88,  87,  88,  87,  87,  87,  88,  87,  87,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 4: Declaration-prime
    (87,   8,   9,  87,  88,  87,  88,  87,  87,  88,  87,  88,  87,  87,  87,  88,  87,  87,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 5: Var-declaration-prime
    (87,  87,  88,  87,  88,  10,  88,  87,  87,  88,  87,  88,  87,  87,  87,  88,  87,  87,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 6: Fun-declaration-prime
    (87,  88,  88,  88,  88,  88,  88,  11,  12,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 7: Type-specifier
    (88,  88,  88,  88,  88,  88,  87,  13,  14,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 8: Params
    (15,  88,  88,  88,  88,  88,  16,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 9: Param-list-void-abtar
    (88,  88,  88,  88,  88,  88,  18,  88,  88,  17,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 10: Param-list
    (88,  88,  88,  88,  88,  88,  87,  19,  19,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 11: Param
    (88,  88,  20,  88,  88,  88,  21,  88,  88,  21,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 12: Param-prime
    (87,  87,  88,  87,  88,  87,  88,  87,  87,  88,  22,  87,  87,  87,  87,  87,  87,  87,  87,  87,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 13: Compound-stmt
    (23,  23,  88,  23,  88,  23,  88,  88,  88,  88,  23,  24,  23,  23,  23,  88,  23,  23,  23,  24,  88,  24,  88,  88,  88,  88,  88,  88,  87), # Row 14: Statement-list
    (25,  25,  88,  25,  88,  25,  88,  88,  88,  88,  26,  87,  25,  25,  27,  87,  28,  29,  30,  87,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 15: Statement
    (31,  34,  88,  31,  88,  31,  88,  88,  88,  88,  87,  87,  32,  33,  87,  87,  87,  87,  87,  87,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 16: Expression-stmt
    (87,  87,  88,  87,  88,  87,  88,  88,  88,  88,  87,  87,  87,  87,  35,  87,  87,  87,  87,  87,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 17: Selection-stmt
    (87,  87,  88,  87,  88,  87,  88,  88,  88,  88,  87,  87,  87,  87,  87,  87,  36,  87,  87,  87,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 18: Iteration-stmt
    (87,  87,  88,  87,  88,  87,  88,  88,  88,  88,  87,  87,  87,  87,  87,  87,  87,  37,  87,  87,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 19: Return-stmt
    (39,  38,  88,  39,  88,  39,  88,  88,  88,  88,  87,  87,  87,  87,  87,  87,  87,  87,  87,  87,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 20: Return-stmt-prime
    (87,  87,  88,  87,  88,  87,  88,  88,  88,  88,  87,  87,  87,  87,  87,  87,  87,  87,  40,  87,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 21: Switch-stmt
    (42,  88,  88,  42,  88,  42,  88,  88,  88,  88,  88,  42,  88,  88,  88,  88,  88,  88,  88,  41,  88,  42,  88,  88,  88,  88,  88,  88,  87), # Row 22: Case-stmts
    (87,  88,  88,  87,  88,  87,  88,  88,  88,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  43,  88,  87,  88,  88,  88,  88,  88,  88,  87), # Row 23: Case-stmt
    (88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  45,  88,  88,  88,  88,  88,  88,  88,  88,  88,  44,  88,  88,  88,  88,  88,  88,  87), # Row 24: Default-stmt
    (47,  87,  88,  46,  87,  46,  87,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 25: Expression
    (88,  50,  49,  88,  50,  50,  50,  88,  88,  50,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  48,  50,  50,  50,  50,  50,  50), # Row 26: B
    (88,  52,  88,  88,  52,  88,  52,  88,  88,  52,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  51,  52,  52,  52,  52,  52,  52), # Row 27: H
    (88,  87,  88,  53,  87,  53,  87,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 28: Simple-expression-zegond
    (88,  54,  88,  88,  54,  54,  54,  88,  88,  54,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  54,  54,  54,  54,  54,  54), # Row 29: Simple-expression-prime
    (88,  56,  88,  88,  56,  88,  56,  88,  88,  56,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  55,  55,  88,  88,  88,  87), # Row 30: C
    (87,  88,  88,  87,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  57,  58,  88,  88,  88,  87), # Row 31: Relop
    (59,  87,  88,  59,  87,  59,  87,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 32: Additive-expression
    (88,  60,  88,  88,  60,  60,  60,  88,  88,  60,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  60,  60,  60,  60,  60,  60), # Row 33: Additive-expression-prime
    (88,  87,  88,  61,  87,  61,  87,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87,  87,  88,  88,  88,  87), # Row 34: Additive-expression-zegond
    (88,  63,  88,  88,  63,  88,  63,  88,  88,  63,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  63,  63,  62,  62,  88,  87), # Row 35: D
    (87,  88,  88,  87,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  64,  65,  88,  87), # Row 36: Addop
    (66,  87,  88,  66,  87,  66,  87,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87,  87,  87,  87,  88,  87), # Row 37: Term
    (88,  67,  88,  88,  67,  67,  67,  88,  88,  67,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  67,  67,  67,  67,  67,  67), # Row 38: Term-prime
    (88,  87,  88,  68,  87,  68,  87,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87,  87,  87,  87,  88,  87), # Row 39: Term-zegond
    (88,  70,  88,  88,  70,  88,  70,  88,  88,  70,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  70,  70,  70,  70,  69,  87), # Row 40: G
    (72,  87,  88,  73,  87,  71,  87,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87,  87,  87,  87,  87,  87), # Row 41: Factor
    (88,  75,  75,  88,  75,  74,  75,  88,  88,  75,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  75,  75,  75,  75,  75,  87), # Row 42: Var-call-prime
    (88,  77,  76,  88,  77,  88,  77,  88,  88,  77,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  77,  77,  77,  77,  77,  87), # Row 43: Var-prime
    (88,  79,  88,  88,  79,  78,  79,  88,  88,  79,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  79,  79,  79,  79,  79,  87), # Row 44: Factor-prime
    (88,  87,  88,  81,  87,  80,  87,  88,  88,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87,  87,  87,  87,  87,  87), # Row 45: Factor-zegond
    (82,  88,  88,  82,  88,  82,  83,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 46: Args
    (84,  88,  88,  84,  88,  84,  87,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87), # Row 47: Arg-list
    (88,  88,  88,  88,  88,  88,  86,  88,  88,  85,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  88,  87)  # Row 48: Arg-list-prime
)


class Parser(object):
    """
    Implements a predictive (LL(1)) parser for the C-minus language.

    The parser takes a stream of tokens from the Scanner and attempts to derive
    them from the grammar's start symbol ("Program") using a set of production
    rules and a parsing table. It constructs a parse tree if the input is
    syntactically correct. If errors are encountered, it attempts error recovery
    using SYNCH symbols and reports syntax errors.

    The parser also triggers semantic actions and code generation routines
    by recognizing special symbols (e.g., #SA_..., #CG_...) embedded in the
    production rules. These actions interface with the SemanticAnalyser and
    CodeGen modules, respectively.
    """
    def __init__(self, input_file):
        """
        Initializes the Parser.

        Args:
            input_file (str): Path to the C-minus source file.
        """
        if not os.path.isabs(input_file):
            input_file = os.path.join(script_dir, input_file) # Ensure path is absolute
        self.scanner = Scanner(input_file)  # Scanner for tokenizing the input file
        self.semantic_analyzer = SemanticAnalyser() # Semantic analyzer instance
        self.code_generator = CodeGen()     # Code generator instance
        self._syntax_errors = []            # List to store (line_number, error_message) tuples
        self.root = Node("Program")         # Root of the parse tree, initialized with the start symbol
        self.parse_tree = self.root
        # Parsing stack, initialized with end-of-input marker '$' and the start symbol 'Program'.
        # Nodes on the stack are `anytree.Node` objects.
        self.stack = [Node("$"), self.root]
        
        # Output file paths
        self.parse_tree_file = os.path.join(script_dir, "output", "parse_tree.txt")
        self.syntax_error_file = os.path.join(script_dir, "errors", "syntax_errors.txt")


    @property    
    def syntax_errors(self):
        """
        Formats and returns all recorded syntax errors.

        Returns:
            str: A string containing all syntax errors, formatted for display or logging.
                 Returns "There is no syntax error.\n" if no errors were found.
        """
        syntax_errors = []
        if self._syntax_errors:
            for lineno, error in self._syntax_errors:
                syntax_errors.append(f"#{lineno} : Syntax Error! {error}\n")
        else:
            syntax_errors.append("There is no syntax error.\n")
        return "".join(syntax_errors)


    def save_parse_tree(self):
        """Saves the constructed parse tree to the parse_tree.txt file."""
        with open(self.parse_tree_file, "w", encoding="utf-8") as f:
            for pre, _, node in RenderTree(self.parse_tree): # RenderTree provides easy tree traversal and printing
                if hasattr(node, "token"): # Leaf nodes representing terminals store the token string
                    f.write(f"{pre}{node.token}\n")
                else: # Internal nodes or non-terminal leaves
                    f.write(f"{pre}{node.name}\n")


    def save_syntax_errors(self):
        """Saves recorded syntax errors to the syntax_errors.txt file."""
        with open(self.syntax_error_file, "w") as f:
            f.write(self.syntax_errors)

    
    def _remove_node(self, node):
        """
        Removes a given node from the parse tree.
        This is a utility function primarily used during error recovery or tree cleanup
        to remove nodes that might have been added based on erroneous parsing paths.

        Args:
            node (anytree.Node): The node to remove from the parse tree.
        """
        try:
            # Get the parent of the node to remove it from its children list.
            # list(node.iter_path_reverse()) gives [node, parent, grandparent, ...], so parent is at index 1.
            parent = list(node.iter_path_reverse())[1]
            parent.children = [c for c in parent.children if c != node]
        except IndexError:
            # This can happen if the node is the root or already detached.
            pass


    def _clean_up_tree(self):
        """
        Removes unfulfilled non-terminal leaf nodes from the parse tree.

        This method iterates through the tree and removes leaf nodes that are
        non-terminals (i.e., they were expected to derive further symbols or
        terminals but didn't, possibly due to syntax errors or reaching EOF
        prematurely) and are not "EPSILON". EPSILON nodes are valid derivations.
        This helps in producing a cleaner parse tree, especially after errors.
        """
        remove_nodes = []
        for node in PreOrderIter(self.parse_tree):
            # A node needs cleanup if it has no children (is a leaf),
            # does not have a 'token' attribute (meaning it's not a matched terminal),
            # and its name is not "EPSILON" (which is a valid terminal derivation).
            if not node.children and not hasattr(node, "token") and node.name != "EPSILON":
                remove_nodes.append(node)
        
        for node in remove_nodes:
            self._remove_node(node)
    

    def parse(self):
        """
        Executes the predictive parsing algorithm.

        The method uses a stack and the pre-defined LL(1) parsing table to
        analyze the token stream from the scanner. It attempts to match input
        tokens with terminals, or expand non-terminals using production rules.

        Algorithm Overview:
        1. Initialize parsing stack with '$' (end-of-input) and 'Program' (start symbol).
        2. Fetch the first token from the scanner.
        3. Loop while the top of the stack (X) is not '$':
            a. Let 'a' be the current input token type.
            b. If X is a semantic action (e.g., #SA_BEGIN_SCOPE):
                Execute the action, pop X.
            c. Else if X is a code generation action (e.g., #CG_GEN_ADD):
                Execute the action, pop X.
            d. Else if X is a terminal:
                If X matches 'a': Pop X, attach token to tree node, get next token.
                Else (mismatch): Report "missing X" error, pop X (panic mode).
            e. Else if X is a non-terminal:
                Consult `parsing_table[X][a]`:
                - If it's a valid production `X -> Y1 Y2 ... Yk`:
                    Pop X. Push Yk, ..., Y2, Y1 onto stack (Y1 on top).
                    Add Y1...Yk as children to X's node in the parse tree.
                - If it's SYNCH: Report "missing construct for X" error, pop X.
                  (Error recovery: assumes X is present and continues).
                - If it's EMPTY/Error: Report "illegal 'a'" error, get next token.
                  (Error recovery: skips illegal token).
        4. After the loop, perform final semantic checks (e.g., EOF checks).
        5. Clean up the parse tree if errors occurred.
        6. Perform final code generation steps.

        Throughout the process, it builds the parse tree and reports errors.
        Semantic actions (#SA_...) and code generation actions (#CG_...) are
        triggered when their symbols are popped from the stack.
        """
        clean_up_needed = False # Flag to indicate if tree cleanup is needed due to errors
        token = self.scanner.get_next_token()
        new_nodes = [] # Temporary list to hold new nodes for a production
        self.code_generator.code_gen("INIT_PROGRAM", None) # Initial code generation setup

        while True:
            token_type, token_value = token
            # For parsing table lookup, 'ID' and 'NUM' are treated as generic types,
            # their actual values (lexims or numbers) are used by semantic actions.
            current_lookahead_type = token_type if token_type not in ("ID", "NUM") else token_type

            current_node_on_stack = self.stack[-1] # Top of the stack
            X = current_node_on_stack.name         # Symbol on top of the stack

            if X.startswith("#SA"):  # Semantic Action Symbol
                # Special handling for #SA_DEC_SCOPE if the lookahead is an ID that needs its scope updated
                # This seems like a context-specific workaround.
                if X == "#SA_DEC_SCOPE" and current_lookahead_type == "ID":
                    curr_lexim = self.scanner.id_to_lexim(token_value)
                self.semantic_analyzer.semantic_check(X, token, self.scanner.line_number)
                self.stack.pop()
                if X == "#SA_DEC_SCOPE" and current_lookahead_type == "ID":
                    # Re-fetch token as its symbol table entry might have been updated (e.g. scope change)
                    token = (token[0], self.scanner.update_symbol_table(curr_lexim))
            elif X.startswith("#CG"):  # Code Generation Action Symbol
                self.code_generator.code_gen(X, token)
                self.stack.pop()
            elif X in terminal_to_col:  # X is a Terminal
                if X == current_lookahead_type:
                    if X == "$": # Successfully parsed if stack top and input are both '$'
                        break
                    # Matched terminal with input token
                    self.stack[-1].token = self.scanner.token_to_str(token) # Annotate parse tree node
                    self.stack.pop()
                    token = self.scanner.get_next_token() # Advance input
                else: # Mismatch between expected terminal and input token
                    SymbolTableManager.error_flag = True
                    if X == "$": # Stack exhausted but input remains
                        self._syntax_errors.append((self.scanner.line_number, "Unexpected input after EOF processing."))
                        break
                    # Report "missing X" error (panic mode: assume X was there and proceed)
                    self._syntax_errors.append((self.scanner.line_number, f'Missing "{X}"'))
                    self.stack.pop() # Pop the expected terminal
                    clean_up_needed = True
            else:  # X is a Non-Terminal
                try:
                    col_idx = terminal_to_col[current_lookahead_type]
                    row_idx = non_terminal_to_row[X]
                    production_index = parsing_table[row_idx][col_idx]
                    rhs_symbols = productions[production_index]

                    if "SYNCH" in rhs_symbols: # Error recovery: synchronize
                        SymbolTableManager.error_flag = True
                        if current_lookahead_type == "$": # Unexpected EOF
                            self._syntax_errors.append((self.scanner.line_number, f"Unexpected EndOfFile, expected {X}"))
                            clean_up_needed = True
                            break
                        # Report "missing construct for X" (panic mode: assume X's construct was there)
                        missing_construct_suggestion = non_terminal_to_missing_construct.get(X, X)
                        self._syntax_errors.append((self.scanner.line_number, f'Missing "{missing_construct_suggestion}"'))
                        self._remove_node(current_node_on_stack) # Remove the problematic non-terminal node
                        self.stack.pop() # Pop non-terminal X
                        # Do not advance token; try to parse with current token and new stack top
                    elif "EMPTY" in rhs_symbols: # Error recovery: skip token
                        SymbolTableManager.error_flag = True
                        self._syntax_errors.append((self.scanner.line_number, f'Illegal "{current_lookahead_type}" for {X}'))
                        token = self.scanner.get_next_token() # Skip current token
                        # Do not pop X; try to parse X with the *next* token
                    else: # Apply production X -> rhs_symbols
                        self.stack.pop()
                        # Add RHS symbols to parse tree and push them onto stack (in reverse order)
                        for symbol_name in rhs_symbols:
                            # Action symbols are not part of the persistent tree structure in the same way,
                            # they are transiently pushed onto the stack.
                            if not symbol_name.startswith("#"):
                                new_nodes.append(Node(symbol_name, parent=current_node_on_stack))
                            else: # Action symbols get plain nodes (no parent initially, handled by stack logic)
                                new_nodes.append(Node(symbol_name))

                        for node_to_push in reversed(new_nodes):
                            if node_to_push.name != "EPSILON": # EPSILON means empty production, don't push
                                self.stack.append(node_to_push)
                            elif node_to_push.name == "EPSILON": # Add Epsilon to tree for completeness
                                node_to_push.parent = current_node_on_stack


                    new_nodes = [] # Reset for next production
                except KeyError:
                    # Should not happen if grammar and tables are consistent & all tokens handled.
                    # This implies current_lookahead_type is not in terminal_to_col, or X not in non_terminal_to_row
                    SymbolTableManager.error_flag = True
                    self._syntax_errors.append((self.scanner.line_number, f'PANIC: Unhandled token "{current_lookahead_type}" or non-terminal "{X}" in parsing table lookup.'))
                    token = self.scanner.get_next_token() # Skip token to attempt recovery
                    if current_lookahead_type == "$": break # Avoid infinite loop at EOF

        # End of parsing loop
        self.semantic_analyzer.eof_check(self.scanner.line_number) # Final semantic checks
        if clean_up_needed:
            self._clean_up_tree()
        self.code_generator.code_gen("FINISH_PROGRAM", None) # Final code generation steps


def main(input_path):
    import time
    SymbolTableManager.init()
    MemoryManager.init()
    parser = Parser(input_path)
    start = time.time()
    parser.parse()
    stop = time.time() - start
    print(f"Parsing took {stop:.6f} s")
    parser.save_parse_tree()
    parser.save_syntax_errors()
    parser.scanner.save_lexical_errors()
    parser.scanner.save_symbol_table()
    parser.scanner.save_tokens()
    parser.semantic_analyzer.save_semantic_errors()
    parser.code_generator.save_output()


if __name__ == "__main__":
    input_path = os.path.join(script_dir, "input/input_simple.c")
    main(input_path)