"""
Lexical Analyzer (Scanner) and Symbol Table Management for the Simple C Compiler.

This module is responsible for two primary functions:
1.  **Lexical Analysis (Scanning):** The `Scanner` class reads the C source code,
    identifies sequences of characters as tokens (e.g., keywords, identifiers,
    numbers, symbols), and passes these tokens to the parser. This process is
    driven by a Deterministic Finite Automaton (DFA).
2.  **Symbol Table Management:** The `SymbolTableManager` class provides a centralized
    way to manage symbols (identifiers like variables and functions) encountered
    during compilation. It handles scopes, ensuring that identifiers are correctly
    resolved based on their declaration context.

Author:             Pasi Pyrrö
Date:               20 March 2020
Modifications:      Added comprehensive docstrings and comments.
"""

import os

script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class SymbolTableManager(object):
    """
    Manages the compiler's symbol table and scope information.

    The symbol table stores information about identifiers (variables, functions)
    encountered in the source code. This includes their name (lexim), scope,
    type, role (e.g., variable, function), arity (for functions), and parameter types.

    This class uses class methods and attributes to provide global access to the
    symbol table and scope stack throughout the compilation process.
    """
    _global_funcs = [{  # Pre-defined global functions, e.g., 'output'
        "lexim": "output",
        "scope": 0,
        "type": "void",
        "role": "function",
        "arity": 1,
        "params": ["int"]
    }]

    @classmethod
    def init(cls):
        """
        Initializes or resets the symbol table and scope management structures.

        This should be called at the beginning of compilation. It sets up:
        - `scope_stack`: Tracks current nesting of scopes. Starts with global scope (0).
        - `temp_stack`: Used for managing temporary variables or similar constructs.
        - `arg_list_stack`: Stack for managing argument lists during function call parsing.
        - `symbol_table`: The main list storing symbol entries. Initialized with global functions.
        - `declaration_flag`: A flag used during parsing to indicate if a declaration is being processed.
        - `error_flag`: A global flag set if any errors occur during compilation.
        """
        cls.scope_stack = [0]  # Stack to keep track of current scope, 0 is global
        cls.temp_stack = [0]
        cls.arg_list_stack = []
        cls.symbol_table = cls._global_funcs.copy()
        cls.declaration_flag = False
        cls.error_flag = False

    @classmethod
    def scope(cls):
        """
        Returns the current scope level.

        The scope level is determined by the size of the scope stack.
        Global scope is 0, the first nested scope is 1, and so on.

        Returns:
            int: The current scope level.
        """
        return len(cls.scope_stack) - 1

    @classmethod
    def insert(cls, lexim):
        """
        Inserts a new symbol (lexim) into the symbol table at the current scope.

        Args:
            lexim (str): The lexical name of the symbol to insert.
        """
        cls.symbol_table.append({"lexim" : lexim, "scope" : cls.scope()})

    @classmethod
    def _exists(cls, lexim, scope):
        """
        Checks if a symbol with the given lexim exists in the specified scope.
        (Internal helper method)

        Args:
            lexim (str): The lexim of the symbol.
            scope (int): The scope level to check within.

        Returns:
            bool: True if the symbol exists in the scope, False otherwise.
        """
        for row in cls.symbol_table:
            if row["lexim"] == lexim and row["scope"] == scope:
                return True
        return False

    @classmethod
    def findrow(cls, value, attr="lexim"):
        """
        Finds and returns the first symbol table entry (row) that matches the
        given attribute and value, searching backwards from the end of the table.

        This is useful for finding the most recently declared symbol that matches,
        respecting scoping (most local declaration).

        Args:
            value: The value to search for.
            attr (str, optional): The attribute (key in the symbol dict) to search by.
                                  Defaults to "lexim".

        Returns:
            dict or None: The symbol table entry (a dictionary) if found, otherwise None.
        """
        for i in range(len(cls.symbol_table) - 1, -1, -1): 
            row = cls.symbol_table[i]
            if row[attr] == value:
                return row
        return None

    @classmethod
    def findrow_idx(cls, value, attr="lexim"):
        """
        Finds and returns the index of the first symbol table entry that matches
        the given attribute and value, searching backwards.

        Args:
            value: The value to search for.
            attr (str, optional): The attribute (key in the symbol dict) to search by.
                                  Defaults to "lexim".

        Returns:
            int or None: The index of the symbol table entry if found, otherwise None.
        """
        for i in range(len(cls.symbol_table) - 1, -1, -1): 
            row = cls.symbol_table[i]
            if row[attr] == value:
                return i
        return None
    
    @classmethod
    def install_id(cls, lexim):
        """
        Gets the index for a given lexim. If not in declaration mode and the
        lexim exists, its existing index is returned. Otherwise, returns the
        index where a new symbol would be inserted (current size of table).

        This method is used to get a unique ID for an identifier, which can
        then be used as the 'value' part of an ID token.

        Args:
            lexim (str): The lexim of the identifier.

        Returns:
            int: The index (ID) for the lexim in the symbol table.
        """
        if not cls.declaration_flag: # If not in declaration, look for existing ID
            i = cls.findrow_idx(lexim)
            if i is not None:
                return i
        return len(cls.symbol_table) # Otherwise, it's a new ID or being declared

    @classmethod
    def get_enclosing_fun(cls, level=1):
        """
        Retrieves the symbol table entry for the enclosing function.

        Args:
            level (int, optional): Specifies which enclosing function to get if
                                   functions are nested (though C-minus doesn't
                                   support full nested functions, this might be
                                   used for tracking the current function context).
                                   Defaults to 1 (the current or innermost function).

        Returns:
            dict or None: The symbol table entry of the enclosing function if found,
                          otherwise None.
        """
        try:
            # The scope_stack stores indices that point to the start of a function's
            # local symbols or parameters within the main symbol_table.
            # The function's own entry is typically right before its parameters/locals.
            return cls.symbol_table[cls.scope_stack[-level] - 1]
        except IndexError:
            return None


# DFA Definitions for Lexical Analysis

# Maps character categories to column indices in the DFA state transition table (token_dfa).
# This categorization simplifies the DFA table structure.
char_to_col = {        # abbreviations in DFA comments:
    "WHITESPACE" : 0,  # w - space, tab, carriage return, etc.
    "DIGIT"      : 1,  # d - 0-9
    "LETTER"     : 2,  # l - a-z, A-Z
    "*"          : 3,  # * - asterisk
    "="          : 4,  # = - equals sign
    "SYMBOL"     : 5,  # s - other symbols like ,, ;, <, etc.
    "/"          : 6,  # / - slash
    "\n"         : 7,  # \n - newline character
    "OTHER"      : 8   # o - (Anything else) typically characters only valid inside a comment block or invalid input
}

# Maps accepting DFA states to their corresponding token types.
# For example, if the DFA ends in state 3, the recognized lexeme is a "NUM" (number).
state_to_token = {
    1  : "WHITESPACE",    # Recognized whitespace
    3  : "NUM",           # Recognized number
    6  : "ID_OR_KEYWORD", # Recognized identifier or keyword (further check needed)
    10 : "SYMBOL",        # Recognized symbol (e.g., ==)
    11 : "SYMBOL",        # Recognized symbol (e.g., =)
    12 : "SYMBOL",        # Recognized symbol (e.g., +, -, <)
    16 : "COMMENT",       # Recognized block comment (/* ... */)
    18 : "COMMENT",       # Recognized single-line comment (// ...)
    19 : "WHITESPACE",    # Recognized newline (treated as whitespace)
    21 : "SYMBOL",        # Recognized symbol (e.g., *)
}

# Maps DFA states that represent errors to a human-readable error message.
state_to_error_message = {
    4  : "illegal number",       # e.g., a number followed by a letter like "123a"
    8  : "unmatched */",         # e.g., seeing "*/" outside of a comment block
    20 : "invalid input",        # Catch-all for unexpected characters in certain states
    22 : "invalid input"         # Specifically for invalid characters after a single '/' that doesn't start a comment
}

# State transition table for the Deterministic Finite Automaton (DFA).
# Each row represents a state.
# Each column corresponds to a character category defined in `char_to_col`.
# The value at `token_dfa[state][char_category_column]` is the next state.
# `None` indicates a transition to an implicit error state (or no valid transition),
# meaning the previously accumulated lexeme (if any, in an accepting state) is recognized,
# or an error is reported if no valid lexeme was formed.
token_dfa = (
    # Columns:
    #   whtspc digt  lettr  *     =   symbl  /    \n   other (see char_to_col)
    #   0     1     2     3     4     5     6     7     8
    (   1,    2,    5,    7,    9,   12,   13,   19,   20), # State 0 (Initial state)
    (   1, None, None, None, None, None, None,    1, None), # State 1 (In Whitespace block)
    (   3,    2,    4,    3,    3,    3,    3,    3,    4), # State 2 (Building a number, e.g., "1", "12")
    (None, None, None, None, None, None, None, None, None), # State 3 (Accept: NUM) - Terminal state for numbers
    (None, None, None, None, None, None, None, None, None), # State 4 (Error: illegal number) - e.g. "12a"
    (   6,    5,    5,    6,    6,    6,    6,    6,   20), # State 5 (Building an ID/Keyword, e.g., "a", "ab")
    (None, None, None, None, None, None, None, None, None), # State 6 (Accept: ID_OR_KEYWORD) - Terminal state for ID/Keyword
    (  21,   21,   21,   21,   21,   21,    8,   21,   20), # State 7 (Saw '*') - could be part of "*/" or just "*"
    (None, None, None, None, None, None, None, None, None), # State 8 (Error: unmatched */) - Saw "*/" not closing a comment
    (  11,   11,   11,   11,   10,   11,   11,   11,   20), # State 9 (Saw '=') - could be part of "==" or just "="
    (None, None, None, None, None, None, None, None, None), # State 10 (Accept: SYMBOL "==")
    (None, None, None, None, None, None, None, None, None), # State 11 (Accept: SYMBOL "=")
    (None, None, None, None, None, None, None, None, None), # State 12 (Accept: SYMBOL, e.g.  '(', ')', '+', etc.)
    (  22,   22,   22,   14,   22,   22,   17,   22,   22), # State 13 (Saw '/') - could start "/*" or "//" or be division (handled by parser for ambiguity)
    (  14,   14,   14,   15,   14,   14,   14,   14,   14), # State 14 (Inside "/*" comment, saw char other than '*')
    (  14,   14,   14,   15,   14,   14,   16,   14,   14), # State 15 (Inside "/*" comment, saw '*' - could be end of comment)
    (None, None, None, None, None, None, None, None, None), # State 16 (Accept: COMMENT "/* ... */")
    (  17,   17,   17,   17,   17,   17,   17,   18,   17), # State 17 (Inside "//" comment, saw char other than \n)
    (None, None, None, None, None, None, None, None, None), # State 18 (Accept: COMMENT "// ... \n")
    (  19, None, None, None, None, None, None,   19, None), # State 19 (Accept: WHITESPACE for newline, potentially consuming more whitespace)
    (None, None, None, None, None, None, None, None, None), # State 20 (Error: invalid input) - e.g. orphan '?'
    (None, None, None, None, None, None, None, None, None), # State 21 (Accept: SYMBOL "*")
    (None, None, None, None, None, None, None, None, None), # State 22 (Error: invalid input after '/') - e.g. "/?"
)

# Set of all accepting states in the DFA.
# If the DFA stops in one of these states, a valid lexeme has been found (or an error explicitly handled by state_to_error_message).
F = {1, 3, 6, 10, 11, 12, 16, 18, 19, 20, 21}

# Set of accepting states where the last character read to reach this state
# is NOT part of the recognized lexeme and must be "returned" to the input stream
# (or, equivalently, the lexeme is all characters *except* the last one).
# This handles lookahead, e.g., for "num*", the "*" is not part of "num".
Fstar = {3, 6, 11, 21}

# States that indicate the scanner is currently inside a block comment.
# If EOF is reached while in one of these states, it's an "unclosed comment" error.
unclosed_comment_states = {14, 15, 17}       # Note: State 17 is for single-line, but EOF logic applies if file ends mid-comment

# Set of whitespace characters, excluding newline which is handled separately by the DFA
# due to its significance in single-line comments and line counting.
whitespaces = {' ', '\r', '\t', '\v', '\f'}


class Scanner(object):
    """
    Lexical analyzer (tokenizer) for the C-minus language.

    The Scanner reads a C-minus source file character by character and groups
    characters into meaningful sequences called lexemes. For each lexeme, it
    produces a token, which is a pair consisting of a token name (e.g., "ID",
    "NUM", "KEYWORD") and an optional attribute value (e.g., the identifier's
    name, the number's value).

    The tokenization process is driven by a Deterministic Finite Automaton (DFA),
    defined by `token_dfa`, `char_to_col`, `state_to_token`, etc.
    It implements the "maximal munch" rule: the longest possible string of
    characters that forms a valid token is chosen.

    The scanner also handles:
    - Ignoring whitespace and comments.
    - Tracking line numbers for error reporting.
    - Storing recognized tokens and lexical errors.
    - Interacting with `SymbolTableManager` to store and retrieve identifiers.
    """

    def __init__(self, input_file, chunk_size=8192, max_state_size=float("inf")):
        """
        Initializes the Scanner.

        Args:
            input_file (str): Path to the C-minus source file.
            chunk_size (int, optional): Size of chunks to read from the file at a time.
                                        Defaults to 8192 bytes. Must be >= 16.
            max_state_size (float, optional): Maximum number of lines of tokens or errors
                                             to keep in memory. Defaults to infinity (keep all).
                                             Used to manage memory for very large files.
        """
        assert chunk_size >= 16, "Minimum supported chunk size is 16!"
        if not os.path.isabs(input_file):
            input_file = os.path.join(script_dir, input_file) # Ensure path is absolute
        self.input_file = input_file
        self.line_number = 1  # Current line number being processed
        self.first_line = 1   # Tracks the first line number currently stored in `self.tokens` (for `max_state_size`)
        self._lexical_errors = [] # Stores tuples of (line_number, lexim, error_message)
        self.tokens = {} # Stores tokens: {line_number: [(token_type, token_value), ...]}
        self.tokens[self.line_number] = []
        self.max_state_size = max_state_size # Max lines of tokens/errors to store

        # File paths for output files
        self.tokens_file = os.path.join(script_dir, "output", "tokens.txt")
        self.symbol_file = os.path.join(script_dir, "output", "symbol_table.txt") # Note: This stores `self.identifiers`
        self.errors_file = os.path.join(script_dir, "errors", "lexical_errors.txt")

        self.chunk_size = chunk_size  # How much of the file to read into `self.input` at once
        self.file_pointer = 0         # Current position in the input file
        self.max_unclosed_comment_size = 15 # Max characters of an unclosed comment to show in error
        self.input = ""               # Current buffer of input characters from the file
        self.read_input()             # Initial read from the file

        # Lexical categories used by the DFA resolver
        self._symbols = {',', ';', ':', '[', ']', '(', ')', '{', '}', '+', '-', '<'} # Base symbols; '*' and '=' handled by DFA states
        self.letters = {chr(i) for i in range(65, 91)} | {chr(i) for i in range(97, 123)} # A-Z, a-z
        self.digits = {str(i) for i in range(0, 10)} # 0-9
        self.symbols = self._symbols | {"*", "="} # Full set of characters treated as symbols by `_resolve_dfa_table_column`
        keywords = [
            "if",           # 0
            "else",         # 1
            "void",         # 2
            "int",          # 3
            "while",        # 4
            "break",        # 5
            "continue",     # 6
            "switch",       # 7
            "default",      # 8
            "case",         # 9
            "return"        # 10
        ]
        self.identifiers = keywords
        self.keywords = set(keywords)


    @property
    def lexical_errors(self):
        """
        Formats and returns all recorded lexical errors.

        Returns:
            str: A string containing all lexical errors, formatted for display or logging.
                 Returns "There is no lexical errors.\n" if no errors were found.
        """
        lexical_errors = []
        if self._lexical_errors:
            for lineno, lexim, error in self._lexical_errors:
                lexical_errors.append(f"#{lineno} : Lexical Error! '{lexim}' rejected, reason: {error}.\n")
        else:
            lexical_errors.append("There is no lexical errors.\n")
        return "".join(lexical_errors)

    
    def save_lexical_errors(self):
        """Saves recorded lexical errors to the lexical_errors.txt file."""
        if self.max_state_size > 0: # Only save if errors were being stored
            with open(self.errors_file, "w") as f:
                f.write(self.lexical_errors)


    def id_to_lexim(self, token_id):
        """
        Retrieves the lexim (string name) of an identifier given its ID
        from the symbol table.

        Args:
            token_id (int): The ID (index) of the token in the SymbolTableManager.symbol_table.

        Returns:
            str: The lexim corresponding to the token_id.
        """
        return SymbolTableManager.symbol_table[token_id]['lexim']

    
    def token_to_str(self, token):
        """
        Converts a token tuple to its string representation for display or logging.
        For ID tokens, it resolves the ID to its lexim.

        Args:
            token (tuple): A token, e.g., ("ID", 0) or ("NUM", "123").

        Returns:
            str: String representation, e.g., "(ID, myVar)" or "(NUM, 123)".
        """
        if token[0] == "ID":
            return f"({token[0]}, {self.id_to_lexim(token[1])})"
        else:
            return "({}, {})".format(*token)


    def read_input(self):
        """
        Reads the next chunk of data from the input file into the `self.input` buffer.

        Raises:
            EOFError: If the end of the file is reached and no more data can be read.
        """
        with open(self.input_file, "rb") as f: # Read as bytes
            f.seek(self.file_pointer)
            chunk = f.read(self.chunk_size)
        if not chunk:
            raise EOFError # Signal end of file if chunk is empty
        self.input += chunk.decode(errors='replace') # Decode bytes to string, replace invalid chars
        self.file_pointer += self.chunk_size


    def _resolve_dfa_table_column(self, input_char):
        """
        Determines the appropriate DFA table column index for a given input character.
        This maps a character to one of the categories defined in `char_to_col`.

        Args:
            input_char (str): The character to categorize.

        Returns:
            int: The column index for the DFA table (`token_dfa`).
        """
        if input_char in whitespaces:
            return char_to_col["WHITESPACE"]
        if input_char in self.letters:
            return char_to_col["LETTER"]
        if input_char in self.digits:
            return char_to_col["DIGIT"]
        if input_char in self._symbols: # Does not include '*', '=', '/'
            return char_to_col["SYMBOL"]
        try:
            # Handles '*', '=', '/', '\n' which have their own columns
            return char_to_col[input_char]
        except KeyError:
            # Any other character (e.g., '?', '%', or chars inside comments)
            return char_to_col["OTHER"]


    def save_symbol_table(self):
        """
        Saves the list of unique identifiers (keywords and user-defined names)
        encountered by the scanner to the symbol_table.txt file.
        Note: This saves `self.identifiers`, which is a list of lexims,
        not the full `SymbolTableManager.symbol_table` which contains more details.
        """
        with open(self.symbol_file, "w") as f:
            for i, symbol_lexim in enumerate(self.identifiers):
                f.write(f"{i+1}.\t{symbol_lexim}\n")


    def save_tokens(self):
        """Saves the recognized tokens (grouped by line number) to the tokens.txt file."""
        if self.max_state_size > 0: # Only save if tokens were being stored
            with open(self.tokens_file, "w") as f:
                for lineno, tokens_on_line in self.tokens.items():
                    if tokens_on_line:
                        f.write(f"{lineno}.\t{' '.join([f'({t}, {l})' for t, l in tokens_on_line])}\n")


    def _switch_line(self, num_lines):
        """
        Updates the scanner's state when one or more newlines are processed.
        Increments `self.line_number`, initializes token storage for new lines,
        and strips leading spaces/tabs from the remaining input buffer.

        Args:
            num_lines (int): The number of newlines encountered.
        """
        if num_lines > 0:
            for i in range(num_lines):
                self.tokens[self.line_number + i + 1] = [] # Prepare token list for new lines
            self.line_number += num_lines
            # Remove leading spaces/tabs from the current input buffer,
            # as they are now at the start of a new line.
            # Newlines themselves are consumed by the DFA or handled by `lexim.count('\n')`.
            self.input = self.input.lstrip(" \t")


    def update_symbol_table(self, lexim):
        """
        Adds a new identifier's lexim to the `SymbolTableManager` if it's not already
        present in the current context (as determined by `install_id`).
        Returns the unique ID (index) for this lexim.

        Args:
            lexim (str): The lexim of the identifier.

        Returns:
            int: The ID (index in `SymbolTableManager.symbol_table`) for this lexim.
        """
        # `install_id` returns existing ID or potential new ID (current table size)
        symbol_id = SymbolTableManager.install_id(lexim)
        # If it's a new ID (i.e., its ID would be the current size of the table),
        # then actually insert it.
        if symbol_id == len(SymbolTableManager.symbol_table):
            SymbolTableManager.insert(lexim) # Inserts with current scope
        return symbol_id


    def get_next_token(self):
        """
        Recognizes and returns the next token from the input stream.

        This is the core method of the Scanner. It uses a DFA (`token_dfa`) to
        find the longest sequence of characters (maximal munch) that forms a
        valid token.

        The process involves:
        1.  Managing input buffering (`read_input` when `self.input` is exhausted).
        2.  Skipping whitespace and comments.
        3.  Iterating through the DFA states based on input characters.
        4.  Handling transitions to error states and reporting lexical errors.
        5.  When an accepting state is reached, determining the token type and value.
        6.  Distinguishing between Identifiers ("ID") and Keywords ("KEYWORD").
        7.  For "ID" tokens, updating and using the `SymbolTableManager`.
        8.  Handling End-Of-File (EOF), including checking for unclosed comments.

        Returns:
            tuple: A token of the form `(TOKEN_TYPE, token_value)`.
                   Examples: `("NUM", "123")`, `("ID", 0)` (where 0 is an ID from
                   `SymbolTableManager`), `("KEYWORD", "if")`, `("EOF", "$")`.
        """
        save_state = None # Stores DFA state if input runs out mid-token
        error_occurred = False
        input_ended = False # Flag if self.input buffer was exhausted during current token scan
        s = 0 # current DFA state, starts at initial state

        # Manage memory by discarding old tokens/errors if max_state_size is exceeded
        if len(self.tokens.keys()) > self.max_state_size:
            self.tokens.pop(self.first_line, None)
            self.first_line += 1
        
        if len(self._lexical_errors) > self.max_state_size:
            self._lexical_errors.pop(0)

        while True: # Loop until a token is returned or EOF
            # Replenish input buffer if empty or exhausted in previous iteration
            if not self.input or input_ended:
                try:
                    self.read_input()
                    input_ended = False # Reset flag after successful read
                except EOFError:
                    # End of file reached
                    if s in unclosed_comment_states: # Check for unclosed comment at EOF
                        mucs = self.max_unclosed_comment_size
                        err_token_preview = self.input[:mucs]
                        if len(self.input) > len(err_token_preview):
                            err_token_preview = err_token_preview + " ..."
                        SymbolTableManager.error_flag = True
                        self._lexical_errors.append((self.line_number, err_token_preview, "unclosed comment"))
                    self.line_number += self.input.count("\n") # Count any remaining newlines
                    self.input = "" # Clear buffer
                    return ("EOF", "$") # Signal End Of File

            token_candidates = [] # Stores (state, lexim) for potential tokens found
            error_occurred = False # Reset for current attempt to find a token

            # Restore DFA state if input was previously exhausted mid-token
            s = 0 if save_state is None else save_state 
            save_state = None

            # --- DFA Traversal ---
            # Iterate through characters in the current input buffer to find the longest match (maximal munch)
            for i in range(len(self.input) + 1): # `+1` allows checking one char ahead for Fstar
                current_char = ''
                if i < len(self.input):
                    current_char = self.input[i]
                # elif i == len(self.input) and s in Fstar: # For Fstar, we need to evaluate the char that caused the transition to None
                    # This case is handled by `next_s is None` or if loop finishes
                # else: # Reached end of current input buffer
                    # This logic is handled by input_ended flag below

                col = self._resolve_dfa_table_column(current_char if current_char else self.input[-1] if self.input else ' ') # Use last char or dummy if at end
                next_s = token_dfa[s][col]

                # Check for error state
                if s in state_to_error_message:
                    lexim_boundary = i
                    if s == 22: # Special lookahead error state for invalid comment starter like "/?"
                        lexim_boundary = i -1 # The error is on the previous character
                    lexim, error_msg = self.input[:lexim_boundary], state_to_error_message[s]
                    if self.max_state_size > 0: # Record error if storing
                        SymbolTableManager.error_flag = True
                        self._lexical_errors.append((self.line_number, lexim, error_msg))
                    else: # Otherwise, print immediately (for debugging or different configurations)
                        print(f"Lexical Error in line {self.line_number}: {error_msg} '{lexim}'")
                    self.input = self.input[lexim_boundary:] # Discard the erroneous part (panic mode recovery)
                    self.line_number += lexim.count("\n") # Adjust line number if error spans lines
                    error_occurred = True
                    break # Restart token search

                # Check if current state `s` is an accepting state
                if s in F:
                    # If state is in Fstar, the current char `a` is not part of this token
                    lexim_end_index = i -1 if s in Fstar and i > 0 else i
                    token_candidates.append((s, self.input[:lexim_end_index]))

                # Check for valid transition
                if next_s is None: # No valid transition from state `s` on `current_char`
                    break # End of current DFA traversal, proceed to process token_candidates

                # Check if end of input buffer is reached
                if i >= len(self.input): # Used all characters in current self.input
                    # If next state is not an accepting one, we might need more input
                    # to complete the current potential token.
                    if next_s not in F:
                        save_state = next_s # Save current state to resume if more input is read
                    input_ended = True # Signal that buffer needs replenishment
                    break # End of current DFA traversal

                s = next_s # Transition to the next state

            # --- End of DFA Traversal for current segment ---

            if error_occurred or input_ended and not token_candidates:
                # If error occurred, or if input ended without forming a candidate (and save_state is set for continuation)
                continue # Restart main while loop (reads more input if input_ended)
            
            if token_candidates:
                # Maximal Munch: select the longest valid token candidate
                final_state, final_lexim = token_candidates[-1]

                self.input = self.input[len(final_lexim):] # Consume the lexim from input buffer
                token_type = state_to_token[final_state]

                num_newlines_in_lexim = final_lexim.count("\n")

                if token_type == "WHITESPACE" or token_type == "COMMENT":
                    self._switch_line(num_newlines_in_lexim) # Update line number, etc.
                    s = 0 # Reset DFA state
                    input_ended = False # Ensure we don't immediately try to read_input unless necessary
                    continue # Ignore whitespace/comments, get next token

                # For non-ignored tokens:
                if token_type == "ID_OR_KEYWORD": # Distinguish between ID and Keyword
                    token_type = "KEYWORD" if final_lexim in self.keywords else "ID"

                if self.max_state_size > 0: # Store token if configured
                    self.tokens[self.line_number].append((token_type, final_lexim))

                token_value = final_lexim
                if token_type == "ID":
                    # For IDs, store the lexim in symbol table (if new) and use its ID as token value
                    if final_lexim not in self.identifiers: # self.identifiers keeps unique lexims for output
                        self.identifiers.append(final_lexim)
                    token_value = self.update_symbol_table(final_lexim) # Get/assign unique ID from SymbolTableManager

                self._switch_line(num_newlines_in_lexim) # Update line number if token spanned lines
                return (token_type, token_value)
            else:
                # No token candidate found, and not an explicit error state from DFA.
                # This implies an unexpected character or sequence not covered by DFA rules.
                # This is a form of panic mode: discard one character and try again.
                if self.input: # Ensure there's input to discard
                    dropped_char = self.input[0]
                    # Report generic error for the unexpected character
                    if self.max_state_size > 0:
                        SymbolTableManager.error_flag = True
                        self._lexical_errors.append((self.line_number, dropped_char, "invalid character"))
                    else:
                        print(f"[Panic Mode] Line {self.line_number}: Dropping unexpected character '{dropped_char}'")

                    if dropped_char == '\n':
                        self._switch_line(1)
                    self.input = self.input[1:] # Discard the character
                else:
                    # Should be caught by EOFError in read_input or start of loop
                    return ("EOF", "$")
                s = 0 # Reset DFA state
                input_ended = False
                continue # Try to get next token

def main(input_path):
    import time
    scanner = Scanner(input_path)
    start = time.time()
    token = scanner.get_next_token()
    while token[0] != "EOF":
        token = scanner.get_next_token()
    stop = time.time() - start
    print(f"Scanning took {stop:.6f} s")
    scanner.save_symbol_table()
    scanner.save_lexical_errors()
    scanner.save_tokens()


if __name__ == "__main__":
    SymbolTableManager.init()
    input_path = os.path.join(script_dir, "input/input_simple.c")
    main(input_path)