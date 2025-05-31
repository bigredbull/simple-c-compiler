"""
Intermediate Code Generator for the Simple C Compiler.

This module is responsible for generating three-address code (TAC) based on
semantic actions triggered by the parser. It manages memory allocation for
variables and temporaries through the `MemoryManager` class and uses information
from the `SymbolTableManager` to resolve identifiers.

The generated TAC is stored in a program block (a list of instructions) and
can be saved to an output file. The generator handles various language
constructs, including assignments, arithmetic and relational operations,
control flow (if/else, while), and function calls with stack frame management.

Author:             Pasi Pyrrö
Date:               1 April 2020
Modifications:      Added comprehensive docstrings and comments.
"""

import os
from scanner import SymbolTableManager

script_dir = os.path.dirname(os.path.abspath(__file__))

class MemoryManager(object):
    """
    Manages memory addresses and offsets for the generated three-address code.

    This is a static class that provides a centralized way to allocate and track
    memory for different segments:
    -   Static data: For global variables, string literals (if any), and fixed addresses
        like the stack frame pointer's own storage.
    -   Temporary variables: For intermediate results of expressions.
    -   Stack frame layout: Manages offsets for parameters, local variables, saved registers,
        return values, etc., within a function's activation record on the runtime stack.

    It maintains base pointers for these segments and current offsets to allocate new
    memory locations sequentially. It also tracks the program block index (`pb_index`)
    which corresponds to the current line number of the generated TAC.
    """

    @classmethod
    def init(cls):
        """
        Initializes or resets all memory pointers and offsets.
        This should be called at the start of the code generation process.
        Sets up base addresses for static data, temporary variables, and the runtime stack.
        Resets offsets and the program block instruction counter.
        """
        cls.static_base_ptr = 1000 # Starting address for static data segment
        cls.temp_base_ptr   = 5000 # Starting address for temporary variables segment
        cls.stack_base_ptr  = 10008# Starting address for the runtime stack

        cls.static_offset   = 0    # Current offset from static_base_ptr
        cls.temp_offset     = 0    # Current offset from temp_base_ptr

        # Offsets within the current function's stack frame (activation record)
        # These are relative to the frame pointer (FP).
        cls.args_field_offset   = 4    # Offset for the first argument (FP + 4 for first arg, FP+0 is access link)
        cls.locals_field_offset = 0    # Offset for local variables (typically negative from FP or positive from SP after locals)
                                       # (Note: current implementation seems to treat these as positive from FP after args/control info)
        cls.arrays_field_offset = 0    # Offset for local arrays
        cls.temps_field_offset  = 0    # Offset for temporary variables spilled to stack (if any)

        cls.pb_index = 0  # Program Block index: current line number of generated TAC


    @classmethod
    def reset(cls):
        """
        Resets offsets related to the current function's stack frame.
        This is typically called after the code generation for a function's body
        (including its stack frame setup) is complete, to prepare for the next function.
        """
        cls.args_field_offset  = 4    # Reset to starting offset for arguments
        cls.locals_field_offset = 0
        cls.array_field_offset = 0   # Note: Mispelling, likely should be arrays_field_offset
        cls.temp_field_offset  = 0


    @classmethod
    def get_temp(cls):
        """
        Allocates space for a new temporary variable in the temporary memory segment
        and returns its absolute memory address.
        Also updates the count of temporary variables used in the current scope
        (tracked in `SymbolTableManager.temp_stack`).

        Returns:
            int: The absolute memory address for the new temporary variable.
        """
        temp_addr = cls.temp_base_ptr + cls.temp_offset
        cls.temp_offset += 4 # Assuming each temporary variable takes 4 bytes
        SymbolTableManager.temp_stack[-1] += 4 # Increment temp usage for current function scope
        return temp_addr


    @classmethod
    def get_static(cls, arity=1):
        """
        Allocates space for a static variable or an array in the static memory segment
        and returns its absolute base memory address.

        Args:
            arity (int, optional): The number of elements if it's an array (each element
                                   assumed to be 4 bytes). Defaults to 1 for simple variables.
        Returns:
            int: The absolute base memory address for the allocated static space.
        """
        static_addr = cls.static_base_ptr + cls.static_offset
        cls.static_offset += 4 * arity # Allocate space based on arity
        return static_addr


    @classmethod
    def get_param_offset(cls, arity=1):
        """
        Calculates and returns the offset for a function parameter within the
        current function's activation record (stack frame).
        The offset is relative to the frame pointer. This method updates
        `args_field_offset` for subsequent parameter offset calculations.

        Args:
            arity (int, optional): The arity of the parameter. Defaults to 1.
                                   (Note: arity is not used in current offset calculation,
                                    as each param slot is assumed fixed size, but might be
                                    for future enhancements like passing structs by value).
        Returns:
            int: The calculated offset for the parameter.
        """
        current_offset = cls.args_field_offset
        cls.args_field_offset += 4 # Move to next parameter slot (assuming 4 bytes per param)
        return current_offset


class CodeGen(object):
    """
    Generates three-address code (TAC) for the C-minus language.

    This class contains routines that are invoked by the parser through semantic
    action symbols (e.g., "#CG_ASSIGN"). These routines construct TAC instructions
    based on the parsed language constructs.

    It uses a `semantic_stack` to hold operands (addresses, constants, symbol table entries)
    and intermediate results needed for generating code for expressions. Other stacks
    (`call_seq_stack`, `cont_label_stack`, `break_loc_stack`) are used to manage
    control flow addresses for backpatching jumps (e.g., in loops and conditional
    statements) and function call sequences.

    The generated TAC instructions are stored in `program_block` and can be written
    to an output file.
    """
    def __init__(self):
        # Stack for holding operands (addresses, constants, symbol table entries) and
        # intermediate results (e.g., address of a temporary variable holding an expression's result)
        # or operator types for TAC generation.
        self.semantic_stack = []
        # Stack used for handling nested or recursive function calls, particularly for backpatching.
        self.call_seq_stack = []
        # Stack to store program block indices for 'continue' statements in loops (for backpatching jumps).
        self.cont_label_stack = []
        # Stack to store program block indices where 'break' statements need to jump out of loops/switches.
        self.break_loc_stack = []

        # Maps code generation action symbols (from parser) to their handler methods.
        self.semantic_routines = {
            "INIT_PROGRAM" : self.init_program_routine,            # Initializes program execution environment (e.g., stack pointer).
            "FINISH_PROGRAM" : self.finish_program_routine,        # Finalizes program, e.g., backpatching main jump.

            # Stack frame and function call/return related routines
            "#CG_CALC_STACKFRAME_SIZE" : self.calc_stackframe_size_routine, # Calculates and stores function's stack frame size.
            "#CG_CALL_SEQ_CALLER" : self.call_seq_caller_routine,          # Generates caller part of function call sequence.
            "#CG_CALL_SEQ_CALLEE" : self.call_seq_callee_routine,          # Generates callee part (setup) of function call.
            "#CG_SET_RETVAL" : self.set_retval_routine,                    # Sets the return value for a function.
            "#CG_RETURN_SEQ_CALLEE" : self.return_seq_callee_routine,      # Generates function return sequence.

            # Operand handling routines
            "#CG_PUSH_ID" : self.push_id_routine,                          # Pushes a symbol table entry (for an ID) onto semantic stack.
            "#CG_PUSH_CONST" : self.push_const_routine,                    # Pushes a constant value (address of) onto semantic stack.

            "#CG_CLOSE_STMT": self.close_stmt_routine,                     # Cleans up semantic stack after an expression statement.

            # Expression and assignment routines
            "#CG_ASSIGN" : self.assign_routine,                            # Generates code for assignment.
            "#CG_MULT" : self.mult_routine,                                # Generates code for multiplication.
            "#CG_SAVE_OP" : self.save_op_routine,                          # Saves an operator token onto semantic stack.
            "#CG_RELOP" : self.relop_routine,                              # Generates code for relational operations.
            "#CG_ADDOP" : self.addop_routine,                              # Generates code for additive operations.

            # Control flow routines (labels, jumps for loops and conditionals)
            "#CG_LABEL" : self.label_routine,                              # Pushes current pb_index (for jump target) onto semantic stack.
            "#CG_SAVE" : self.save_routine,                                # Saves current pb_index and adds placeholder for future jump.
            "#CG_WHILE" : self.while_routine,                              # Generates code for 'while' loop condition and jumps.

            "#CG_IF_ELSE" : self.if_else_routine,                          # Backpatches jump after 'if' block (for if-else).
            "#CG_ELSE" : self.else_routine,                                # Backpatches jump for 'if' condition, saves 'else' jump placeholder.

            # Loop control statement support
            "#CG_INIT_WHILE_STACKS" : self.init_while_stacks_routine,      # Initializes stacks for 'continue' and 'break' for a while loop.
            "#CG_CONT_JP" : self.cont_jp_routine,                          # Generates jump for 'continue' statement.
            "#CG_BREAK_JP_SAVE" : self.break_jp_save_routine,              # Saves placeholder for 'break' statement jump.
        }

        # Maps operator tokens from the scanner to their corresponding TAC opcodes.
        self.token_to_op = {
            "+"  : "ADD",  # Addition
            "-"  : "SUB",  # Subtraction
            "==" : "EQ",   # Equal to
            "<"  : "LT"    # Less than
        }

        # List to store the generated three-address code instructions.
        # Each element is a tuple: (line_number, tac_string).
        self.program_block = []

        # Path to the output file where the generated TAC will be saved.
        self.output_file = os.path.join(os.path.dirname(script_dir), "output", "output.txt")

    
    @property
    def stack_frame_ptr_addr(self):
        """
        Returns the predefined memory address where the runtime stack frame pointer (FP) is stored.
        This is a fixed static memory location.
        """
        return MemoryManager.static_base_ptr


    @property
    def print_addr(self):
        """
        Returns the predefined memory address used as the operand for the special 'PRINT' TAC instruction.
        The value to be printed is first assigned to this memory location.
        """
        return MemoryManager.static_base_ptr + 4 # Typically allocated right after FP storage


    @property
    def arg_counter(self):
        """
        Returns a list containing the number of arguments for each active function call context.
        This information is derived from `SymbolTableManager.arg_list_stack`.
        """
        return [len(l) for l in SymbolTableManager.arg_list_stack]


    def _add_three_addr_code(self, three_addr_code, idx=None, insert=False, increment=True):
        """
        Adds a three-address code instruction to the program block.

        Args:
            three_addr_code (str or tuple): The TAC instruction string, or a tuple
                                           (opcode, arg1, arg2, arg3) to be formatted.
            idx (int, optional): The program block index where the instruction should be
                                 placed. If None, appends to the end. Defaults to None.
            insert (bool, optional): If True and idx is provided, replaces the instruction
                                     at idx (used for backpatching). Defaults to False.
            increment (bool, optional): If True, increments `MemoryManager.pb_index`.
                                        Set to False when backpatching an existing line.
                                        Defaults to True.
        """
        if idx is None:
            idx = MemoryManager.pb_index
        if isinstance(three_addr_code, tuple): # If given as (opcode, arg1, ...), format it
            three_addr_code = self._get_three_addr_code(three_addr_code[0], *three_addr_code[1:])

        if insert: # Replace instruction at idx (for backpatching)
            self.program_block[idx] = (idx, three_addr_code)
        else: # Append new instruction
            self.program_block.append((idx, three_addr_code))

        if increment:
            MemoryManager.pb_index += 1


    def _add_placeholder(self):
        """Adds a placeholder instruction to the program block, to be backpatched later."""
        self._add_three_addr_code("PLACEHOLDER")

    
    def _add_print_code(self, t):
        """
        Generates the special 'PRINT' three-address code instruction.
        't' is the address of the value to be printed.
        """
        self._add_three_addr_code(self._get_three_addr_code("print", t))

    
    def _get_three_addr_code(self, opcode, *args):
        """
        Formats an opcode and its arguments into a standard TAC string.
        Example: (ADD, R1, R2, R3) -> "(ADD, R1, R2, R3)"

        Args:
            opcode (str): The operation code (e.g., "ADD", "ASSIGN").
            *args: Up to three arguments for the operation.

        Returns:
            str: The formatted three-address code string.
        """
        three_addr_code = "(" + opcode.upper()
        for i in range(3): # TAC typically has up to 3 operands
            try:
                arg = args[i]
                three_addr_code = three_addr_code + ", " + str(arg)
            except IndexError: # If fewer than 3 args, fill with blanks
                three_addr_code = three_addr_code + ", "
        return three_addr_code + ")"


    def _get_context_info(self):
        """Helper to get current scope stack and symbol table from SymbolTableManager."""
        scope_stack = SymbolTableManager.scope_stack
        symbol_table = SymbolTableManager.symbol_table
        return scope_stack, symbol_table


    def _get_enclosing_fun(self, level=1):
        """
        Retrieves the symbol table entry for the current (or an enclosing) function.
        Args:
            level (int): 1 for current function, 2 for its enclosing function, etc.
        Returns:
            dict or None: The function's symbol table entry, or None if not found.
        """
        try:
            scope_stack = SymbolTableManager.scope_stack
            symbol_table = SymbolTableManager.symbol_table
            # Assumes function entry is right before its scope starts in symbol_table
            return symbol_table[scope_stack[-level] - 1]
        except IndexError:
            return None


    def _get_add_code(self, *args):
        """Shortcut to format an ADD instruction string."""
        return self._get_three_addr_code("ADD", *args)

    
    def _get_sub_code(self, *args):
        """Shortcut to format a SUB instruction string."""
        return self._get_three_addr_code("SUB", *args)

    
    def _get_static_addr(self, offset):
        """Calculates an absolute static memory address given a base and an offset."""
        return MemoryManager.static_base_ptr + offset

    
    def _resolve_addr(self, operand):
        """
        Resolves an operand from the semantic stack to its actual address or immediate value for TAC.
        - If operand is an int: it's likely already an address (e.g., from MemoryManager.get_temp()).
        - If operand is a dict (symbol table row) with "address": it's a statically known address.
        - If operand is a dict with "offset": it's a stack variable (local/param).
          Generates TAC to calculate its dynamic address (FramePointer + offset) and stores
          this address in a new temporary. The address of this temporary (indirect addressing, e.g. @temp)
          is then returned.

        Args:
            operand: The operand to resolve (int, or dict from symbol table).

        Returns:
            str or int: The resolved address (e.g., 1024, @5004) or immediate value (e.g., #5).
        """
        if isinstance(operand, int): # Already an address (e.g. a temporary's address)
            addr = operand
        elif "address" in operand: # Statically known address (global var, or static temp from push_const)
            addr = operand["address"]
        else: # Dynamically addressed: local variable or parameter on stack
            # Calculate dynamic address: FP + offset
            t_dyn_addr_holder = MemoryManager.get_temp() # Temp to hold the calculated address
            # (ADD, FP_addr, #offset, t_dyn_addr_holder)
            self._add_three_addr_code(self._get_add_code(self.stack_frame_ptr_addr, f"#{operand['offset']}", t_dyn_addr_holder))
            addr = f"@{t_dyn_addr_holder}" # Use indirect addressing for the TAC operand
        return addr


    def save_output(self):
        """Saves the generated program_block (list of TAC instructions) to the output file."""
        with open(self.output_file, "w") as f:
            if self.program_block:
                for lineno, three_addr_code in self.program_block:
                    f.write(f"{lineno}\t{three_addr_code}\n")
            else:
                f.write("Failed to generate output program.\n")


    # ---                         CODE GENERATION ROUTINES                             --- #
    # These methods are called by self.code_gen() based on #CG_... symbols from the parser.
    # `input_token` is often unused as info is typically on `self.semantic_stack`.
    # ---                                                                              --- #


    def push_const_routine(self, input_token):
        """
        Generates code to store a constant value in a new static memory location.
        The address of this location is pushed onto the semantic stack.
        Triggered by: Encountering a NUM token that is part of an expression.
        TAC: (ASSIGN, #const_val, static_addr_for_const)
        """
        addr = MemoryManager.get_static() # Allocate static memory for the constant
        const_val_str = "#" + input_token[1] # Immediate value prefix
        self._add_three_addr_code(self._get_three_addr_code("assign", const_val_str, addr))
        self.semantic_stack.append(addr) # Push address of the constant


    def push_id_routine(self, input_token):
        """
        Pushes the symbol table entry (a dict) of an ID onto the semantic stack.
        This ID will be used as an operand in subsequent TAC generation.
        Triggered by: Encountering an ID token that is part of an expression.
        """
        id_row = SymbolTableManager.symbol_table[input_token[1]] # Get symbol's attributes
        self.semantic_stack.append(id_row)

    
    def init_program_routine(self, input_token):
        """
        Initializes the program's runtime environment.
        - Assigns the starting address of the runtime stack to the stack frame pointer (FP).
        - Allocates static space for FP storage and the special print address.
        - Adds placeholders for jumping to 'main' and setting up its return, to be backpatched later.
        TAC:
            (ASSIGN, #stack_base_addr, fp_storage_addr)
            ... (placeholders for main jump setup) ...
        """
        # (ASSIGN, #stack_start_addr, fp_addr)
        three_addr_code = self._get_three_addr_code("assign", f"#{MemoryManager.stack_base_ptr}", 
                                  self.stack_frame_ptr_addr)
        self._add_three_addr_code(three_addr_code)
        # Allocate space for stack_frame_ptr_addr itself and print_addr
        MemoryManager.static_offset += 8 # FP (addr 1000) and Print (addr 1004)
        # Placeholders for jumping to main, to be backpatched by finish_program_routine
        for _ in range(3): # Reserve 3 lines for main jump setup
            self._add_placeholder()
        

    def assign_routine(self, input_token):
        """
        Generates code for an assignment operation (dest = source).
        Pops source operand (A) and destination operand (R, which is an ID row) from semantic stack.
        Resolves their addresses and generates TAC.
        Triggered by: An assignment production.
        TAC: (ASSIGN, resolved_source_addr, resolved_dest_addr)
        """
        try:
            source_operand = self.semantic_stack.pop()
            dest_operand_info = self.semantic_stack[-1] # Destination is an ID, peek it

            A = self._resolve_addr(source_operand) # Address of source
            R = self._resolve_addr(dest_operand_info)  # Address of destination
            self._add_three_addr_code(("assign", A, R))
        except IndexError:
            # Error: Not enough operands on stack (should be caught by parser/semantic analysis)
            pass

    
    def save_op_routine(self, input_token):
        """
        Saves an operator's TAC mnemonic (e.g., "ADD", "EQ") onto the semantic stack.
        The operator token (e.g., "+", "==") is mapped to its TAC equivalent.
        Triggered by: Encountering an operator token in an expression.
        """
        op_mnemonic = self.token_to_op[input_token[1]] # Convert token like "+" to "ADD"
        self.semantic_stack.append(op_mnemonic)


    def mult_routine(self, input_token):
        """Generates code for multiplication. Calls `binary_op_routine` with "MULT"."""
        self.binary_op_routine("MULT")


    def relop_routine(self, input_token):
        """
        Generates code for a relational operation (e.g., <, ==).
        Pops operator from stack (was pushed by `save_op_routine` before RHS operand).
        Then calls `binary_op_routine` with the specific relational operator.
        """
        try:
            # Operator was pushed before the second operand, so it's at stack[-2]
            # before operands are processed by binary_op_routine.
            op = self.semantic_stack.pop(-2) # Pop operator (e.g. "LT", "EQ")
            self.binary_op_routine(op)
        except IndexError:
            pass # Error: stack issue
    

    def addop_routine(self, input_token):
        """
        Generates code for an additive operation (e.g., +, -).
        Pops operator from stack. Calls `binary_op_routine`.
        """
        try:
            op = self.semantic_stack.pop(-2) # Pop operator (e.g. "ADD", "SUB")
            self.binary_op_routine(op)
        except IndexError:
            pass # Error: stack issue


    def binary_op_routine(self, op):
        """
        Generates code for a generic binary operation (op, A1, A2, R).
        Pops two operands (A2, then A1) from semantic stack, resolves their addresses.
        Allocates a temporary (R) for the result. Generates TAC.
        Pushes the result's address (R) back onto semantic stack.
        TAC: (op, resolved_A1, resolved_A2, temp_R_addr)
        """
        try:
            R_addr = MemoryManager.get_temp() # Temp for the result
            A2_operand = self.semantic_stack.pop()
            A1_operand = self.semantic_stack.pop()

            A2 = self._resolve_addr(A2_operand)
            A1 = self._resolve_addr(A1_operand)

            self._add_three_addr_code((op, A1, A2, R_addr))
            self.semantic_stack.append(R_addr) # Push result address
        except IndexError:
            pass # Error: stack issue


    def finish_program_routine(self, input_token):
        """
        Finalizes the program code, primarily by backpatching the jump to 'main'.
        The initial placeholders (lines 1, 2, 3) are filled:
        1. Calculate main's return address storage on stack.
        2. Store the starting address of 'main's actual code into this return address slot.
           (This seems to be storing current PB index as return address for main, which is unusual.
            Typically main's "return" is to OS or runtime exit).
        3. Jump to 'main's actual starting address.
        This routine seems to be setting up a simulated return from main.
        """
        # Backpatch the jump to main function (assumed to be at lines 1, 2, 3)
        t_ret_addr_storage_for_main = MemoryManager.get_temp()
        # Line 1: Calculate where main's "return address" would be stored (e.g. FP_main - 4)
        # This simulates setting up a return address for main, though main usually exits.
        # (SUB, fp_addr, #4, t_ret_addr_storage_for_main) ; effectively FP_main_base - 4
        self.program_block[1] = (1, self._get_sub_code(self.stack_frame_ptr_addr, "#4", t_ret_addr_storage_for_main))

        # Line 2: Store the address *after* the main routine (current pb_index) into this "return address" slot.
        # This means if main "returns", it jumps to the end of the generated code.
        # (ASSIGN, #current_pb_end, @t_ret_addr_storage_for_main)
        self.program_block[2] = (2, self._get_three_addr_code("assign", f"#{MemoryManager.pb_index}", f"@{t_ret_addr_storage_for_main}"))

        # Line 3: Unconditional jump to the actual starting address of 'main' function.
        # (JP, main_start_addr)
        self.program_block[3] = (3, self._get_three_addr_code("jp", SymbolTableManager.findrow("main")["address"]))


    def call_seq_caller_routine(self, input_token, backpatch=False):
        """
        Generates the caller's sequence for a function call.
        Manages stack frame adjustments, argument passing, and the jump to callee.
        Handles both normal calls and backpatching for recursive/forward-declared calls.

        Stack expectations before this routine (simplified):
        [..., fun_sym_entry, arg1_addr, arg2_addr, ..., argN_addr] (top)

        Generated TAC (simplified):
        1. Calculate new Frame Pointer (FP_new = FP_current + current_frame_size).
        2. Store current FP (access link) at FP_new + 0.
        3. Store arguments at FP_new + offset_arg1, ...
        4. Update FP_current = FP_new.
        5. Store return address (current_pb_index + 2) at FP_current - 4 (relative to new FP).
        6. Jump to function's code address.
        7. (After return) Retrieve return value (from FP_current - 8).
        8. Restore FP_current = FP_current - current_frame_size (i.e. old FP from access link).
        Pushes address of return value temp onto semantic_stack if function is not void.
        """
        # `stack` refers to `self.semantic_stack` or `self.call_seq_stack` (for backpatching)
        stack = self.semantic_stack if not backpatch else self.call_seq_stack

        if backpatch: # Restoring state for a previously deferred call sequence
            callee = stack.pop() # Callee's symbol table entry
            store_idx = MemoryManager.pb_index # Save current pb_index to restore later
            t_ret_val = stack.pop() # Pre-allocated temp for return value
            self.arg_counter[-1] = stack.pop() # Number of args for this call
            MemoryManager.pb_index = stack.pop() # Restore pb_index to where this call's code should be inserted
        else: # Standard call sequence generation
            # Callee is (N+1)th item from top of semantic_stack, where N is num_args
            callee = stack[-(self.arg_counter[-1] + 1)]
        
        caller = SymbolTableManager.get_enclosing_fun() # Current function making the call

        # Special handling for built-in "output" function
        if callee["lexim"] == "output":
            arg_operand = stack.pop() # Pop argument for output
            stack.pop() # Pop "output" function symbol itself
            arg_addr = self._resolve_addr(arg_operand)
            self._add_three_addr_code(self._get_three_addr_code("assign", arg_addr, self.print_addr))
            self._add_three_addr_code(self._get_three_addr_code("PRINT", self.print_addr))
            self.arg_counter[-1] = 0 # Reset arg count for current context
            self.semantic_stack.append("void") # 'output' returns void
            return

        if not backpatch: # Allocate temp for return value if not already done (for backpatching)
            t_ret_val = MemoryManager.get_temp()
        
        # Ensure caller's frame size is known (should be set by calc_stackframe_size_routine)
        if "frame_size" in caller:
            current_fp_addr = self.stack_frame_ptr_addr # Address where current FP is stored
            caller_frame_size = caller["frame_size"]

            # 1. Calculate new Frame Pointer for callee: new_fp = current_fp + caller_frame_size
            t_new_fp = MemoryManager.get_temp()
            self._add_three_addr_code(self._get_add_code(current_fp_addr, f"#{caller_frame_size}", t_new_fp), insert=backpatch)

            # 2. Store Access Link: (ASSIGN, current_fp_addr, @t_new_fp) ; new_fp[0] = current_fp
            self._add_three_addr_code(self._get_three_addr_code("assign", current_fp_addr, f"@{t_new_fp}"), insert=backpatch)

            # 3. Store arguments into callee's frame
            t_arg_base_in_callee_frame = MemoryManager.get_temp()
            # Args start at new_fp + 4 (offset for first arg)
            self._add_three_addr_code(self._get_add_code(t_new_fp, "#4", t_arg_base_in_callee_frame), insert=backpatch)

            num_args = callee["arity"]
            args_on_stack = stack[-num_args:] # Get arg operands from stack

            for i in range(num_args):
                stack.pop() # Pop each arg from semantic_stack
                arg_operand = args_on_stack[i]
                arg_val_addr = self._resolve_addr(arg_operand)

                # For array parameters, pass their base address directly (pass-by-reference like behavior)
                if callee["params"][-i-1] == "array": # Check type of corresponding param
                     # If arg_operand is an ID for an array, its 'address' is the base.
                     # If it's a temp from an expression, this is tricky; C-minus might not support complex array expressions as args.
                     # Assuming simple array ID pass or pointer. Current _resolve_addr gives address.
                     # For pass-by-reference, we need the *address* of the array, not its content.
                     # If arg_operand is an array symbol, its .address is what we want.
                     # If arg_val_addr is @temp, it means temp holds the value, not address of an array.
                     # This part needs careful review of how array arguments are represented.
                     # Assuming arg_operand['address'] for arrays if it's an ID.
                     # If it's a parameter itself being passed, its offset needs careful handling.
                     # The example code uses f"#{arg_operand}" which might be a placeholder for its actual address.
                     # This is simplified here to use the resolved address.
                     pass_addr = f"#{arg_operand['address']}" if isinstance(arg_operand, dict) and arg_operand.get("type") == "array" else arg_val_addr

                # (ASSIGN, arg_val_addr, @(t_arg_base_in_callee_frame + i*4))
                self._add_three_addr_code(self._get_three_addr_code("assign", arg_val_addr, f"@{t_arg_base_in_callee_frame}"), insert=backpatch)
                if i < num_args - 1: # For all but last arg, advance arg pointer in callee frame
                    self._add_three_addr_code(self._get_add_code(t_arg_base_in_callee_frame, "#4", t_arg_base_in_callee_frame), insert=backpatch)

            fun_sym_entry_on_stack = stack.pop() # Pop function symbol itself
            callee_code_addr = fun_sym_entry_on_stack["address"]

            # 4. Store Return Address: ret_addr_storage = new_fp - 4 ; new_fp[-1]
            t_ret_addr_storage_loc = MemoryManager.get_temp()
            self._add_three_addr_code(self._get_sub_code(t_new_fp, "#4", t_ret_addr_storage_loc), insert=backpatch)
            # (ASSIGN, #(current_pb + 2 lines for this assign and JP), @t_ret_addr_storage_loc)
            self._add_three_addr_code(self._get_three_addr_code("assign", f"#{MemoryManager.pb_index + 2}", f"@{t_ret_addr_storage_loc}"), insert=backpatch)

            # Temp for callee to store its return value: ret_val_storage = new_fp - 8 ; new_fp[-2]
            t_ret_val_storage_loc_in_callee = MemoryManager.get_temp()
            self._add_three_addr_code(self._get_sub_code(t_new_fp, "#8", t_ret_val_storage_loc_in_callee), insert=backpatch)

            # 5. Update FP: current_fp = new_fp
            self._add_three_addr_code(self._get_three_addr_code("assign", t_new_fp, current_fp_addr), insert=backpatch)

            # 6. Jump to function's code address
            self._add_three_addr_code(self._get_three_addr_code("jp", callee_code_addr), insert=backpatch)

            # -- Code after function returns --
            # 7. Retrieve return value: t_ret_val = @t_ret_val_storage_loc_in_callee
            self._add_three_addr_code(self._get_three_addr_code("assign", f"@{t_ret_val_storage_loc_in_callee}", t_ret_val), insert=backpatch)

            # 8. Restore FP: current_fp = current_fp - caller_frame_size (or more simply, current_fp = @current_fp (access link))
            # The code uses subtract, implying frame_size is accurate for FP restoration.
            # A common way is (ASSIGN, @current_fp_addr, current_fp_addr) to restore from access link.
            # The provided code calculates current_fp - frame_size.
            self._add_three_addr_code(self._get_sub_code(current_fp_addr, f"#{caller_frame_size}", current_fp_addr), insert=backpatch)

        else: # Caller's frame size not known (e.g., recursive call before frame calculation)
              # Defer code generation by saving state to call_seq_stack for later backpatching.
            callee_sym_entry = stack[-(self.arg_counter[-1] + 1)]
            # Save all operands and necessary info for backpatching
            self.call_seq_stack.extend(self.semantic_stack[-(self.arg_counter[-1] + 1):]) # Save func entry + args

            num_offset_vars = 0 # Count args that are stack offsets (need dynamic address resolution)
            for i in range(1, callee_sym_entry["arity"] + 1):
                arg = self.semantic_stack[-i]
                if not isinstance(arg, int) and "offset" in arg: # Check if arg is a symbol table row with an offset
                    num_offset_vars += 1
            
            self.semantic_stack = self.semantic_stack[:-(self.arg_counter[-1] + 1)] # Clear them from current stack

            # Save context for backpatching
            self.call_seq_stack.append(MemoryManager.pb_index) # Current instruction index to start inserting backpatched code
            self.call_seq_stack.append(self.arg_counter[-1])   # Number of arguments
            self.call_seq_stack.append(t_ret_val)              # Temp allocated for return value
            self.call_seq_stack.append(callee_sym_entry)       # Callee symbol info

            # Reserve placeholder lines for the call sequence TAC (approximate number)
            # Needs to be enough for: new_fp calc, access link, arg assignments, ret_addr, ret_val_loc, fp update, jp, retval fetch, fp restore.
            # Each arg might take 1 (direct) or 2 (indirect via offset) ASSIGNs, plus one ADD for arg ptr.
            # Rough estimate: 10 fixed + arity*(1 for assign + 1 for ptr add) + num_offset_vars*(1 for addr calc)
            num_placeholders = 10 + callee_sym_entry.get("arity",0) * 2 + num_offset_vars
            for _ in range(num_placeholders):
                self._add_placeholder()

        if backpatch: # If backpatching, restore original pb_index
            MemoryManager.pb_index = store_idx
        else: # If not backpatching, push result type/temp onto semantic stack
            if callee.get("type") == "void":
                self.semantic_stack.append("void") # Placeholder for void return
            else:
                self.semantic_stack.append(t_ret_val) # Push address of temp holding return value

        
    def call_seq_callee_routine(self, input_token):
        """
        Generates the callee's setup sequence at the beginning of a function's code.
        Currently, this routine is a placeholder. In a more complete system, it might
        involve saving registers or further stack adjustments if not fully handled by caller.
        Array pointer setup for parameters passed by reference could also happen here.
        """
        pass # TODO: assign array pointers here (if params are arrays passed by reference)


    def calc_stackframe_size_routine(self, input_token):
        """
        Calculates and stores the total stack frame size for the current function.
        This includes space for arguments, local variables, arrays, and compiler temporaries.
        The sizes and offsets are stored in the function's symbol table entry.
        After calculating, it processes any deferred (backpatched) call sequences.
        Resets `MemoryManager` offsets for the next function.
        """
        scope_stack, symbol_table = self._get_context_info()
        fun_row = SymbolTableManager.get_enclosing_fun() # Get current function's symbol entry

        # Initialize size accumulators
        fun_row["args_size"] = 0    # Size of arguments area (already set by param processing conceptually)
        fun_row["locals_size"] = 0  # Size of local variables
        fun_row["arrays_size"] = 0  # Size of local arrays
        fun_row["temps_size"] = SymbolTableManager.temp_stack.pop() # Get size of temps used in this func
        if not SymbolTableManager.temp_stack: # Ensure stack is not empty if this was the only scope
            SymbolTableManager.temp_stack = [0]

        # Iterate over symbols declared in the current function's scope
        for i in range(scope_stack[-1], len(symbol_table)):
            sym = symbol_table[i]
            if sym["role"] == "local_var":
                if sym["type"] == "array":
                    fun_row["arrays_size"] += 4 * sym["arity"]
                # Each simple local var takes 4 bytes (even if array base, separate space for array itself)
                fun_row["locals_size"] += 4 # This might be double counting array base if not careful
            elif sym["role"] == "param": # Arity for params is usually 1 per param entry
                fun_row["args_size"] += 4 * sym.get("arity", 1) # Summing up param sizes

        # Total frame size: args + control info (ret addr, ret val loc, access link) + locals + arrays + temps
        # Control info = 3 items * 4 bytes/item = 12 bytes (Return Addr, Return Val, Access Link)
        fun_row["frame_size"] = fun_row["args_size"] + fun_row["locals_size"] \
                              + fun_row["arrays_size"] + fun_row["temps_size"] + 12

        # Store offsets for different parts of the frame (relative to FP)
        # FP+0: Access Link
        # FP+4: First argument
        fun_row["args_offset"] = 4 # Start of arguments
        # FP - 4: Return Address storage (conventionally)
        # FP - 8: Return Value storage (conventionally)
        # These are handled by fixed offsets from FP in call/return sequences.
        # Local variable offsets would typically be negative from FP or positive from SP after allocation.
        # The current model seems to place locals after args relative to FP.
        fun_row["locals_offset"] = fun_row["args_offset"] + fun_row["args_size"]
        fun_row["arrays_offset"] = fun_row["locals_offset"] + fun_row["locals_size"]
        fun_row["temps_offset"] = fun_row["arrays_offset"] + fun_row["arrays_size"]
        
        # Process any deferred function calls that needed this function's frame size
        while self.call_seq_stack:
            self.call_seq_caller_routine(input_token, backpatch=True)

        MemoryManager.reset() # Reset stack frame part offsets for the next function

    
    def set_retval_routine(self, input_token):
        """
        Generates code to store a function's return value.
        The return value (from semantic_stack) is assigned to the designated
        return value slot in the caller's stack frame (FP - 8).
        If no expression for return (void return or empty return), assigns #0.
        TAC: (ASSIGN, resolved_retval_addr_or_#0, @(fp_addr - #8))
        """
        # Temp to hold address of return value slot (current_FP - 8)
        t_ret_val_slot_addr = MemoryManager.get_temp()
        self._add_three_addr_code(self._get_sub_code(self.stack_frame_ptr_addr, "#8", t_ret_val_slot_addr))

        try:
            # Resolve address of the expression providing the return value
            retval_addr = self._resolve_addr(self.semantic_stack.pop())
        except IndexError: # No return value expression on stack (e.g. 'return;' in void func or error)
            # Assign 0 to the return value slot if no expression given (or if function is void and returns).
            # For a truly void function, this might not be strictly necessary if caller ignores it.
            tac_instr = self._get_three_addr_code("assign", "#0", f"@{t_ret_val_slot_addr}")
            self._add_three_addr_code(tac_instr)
        else:
            # Assign the computed return value to the return value slot
            tac_instr = self._get_three_addr_code("assign", retval_addr, f"@{t_ret_val_slot_addr}")
            self._add_three_addr_code(tac_instr)


    def return_seq_callee_routine(self, input_token):
        """
        Generates the callee's return sequence.
        Retrieves the stored return address (from FP - 4) and jumps to it.
        TAC:
            (SUB, fp_addr, #4, t_ret_addr_loc)  ; Get location of stored return address
            (ASSIGN, @t_ret_addr_loc, t_actual_ret_addr) ; Get actual return address
            (JP, @t_actual_ret_addr)             ; Jump to it
        """
        t_ret_addr_slot_addr = MemoryManager.get_temp() # Temp to hold address of RetAddr slot (FP-4)
        self._add_three_addr_code(self._get_sub_code(self.stack_frame_ptr_addr, "#4", t_ret_addr_slot_addr))

        t_actual_ret_addr = MemoryManager.get_temp() # Temp to hold the actual return address value
        self._add_three_addr_code(self._get_three_addr_code("assign", f"@{t_ret_addr_slot_addr}", t_actual_ret_addr))

        # Jump to the actual return address
        self._add_three_addr_code(self._get_three_addr_code("jp", f"@{t_actual_ret_addr}"))
    

    def close_stmt_routine(self, input_token):
        """
        Cleans up the semantic stack after an expression statement.
        If an expression statement results in a value (e.g., an assignment expression),
        that result (its address) might be left on the semantic_stack. This pops it,
        as the value of a standalone expression statement is usually not used further.
        """
        if self.semantic_stack:
            # Pop result of last expression if it was an expression statement
            # (e.g. result of assignment if it was used as `a = b;`)
            self.semantic_stack.pop()

    
    def label_routine(self, input_token):
        """
        Pushes the current program block index (MemoryManager.pb_index) onto the
        semantic stack. This index is used as a target for jump instructions (e.g., start of a loop).
        """
        self.semantic_stack.append(MemoryManager.pb_index)


    def save_routine(self, input_token):
        """
        Saves the current program block index (for backpatching) onto the semantic stack
        and adds a placeholder instruction in the program block.
        Used for conditional jumps where the target address is not yet known.
        """
        self.semantic_stack.append(MemoryManager.pb_index) # Save current line for backpatching
        self._add_placeholder() # Add a placeholder TAC that will be filled later


    def while_routine(self, input_token):
        """
        Generates code for a 'while' loop's control flow.
        Pops elements from semantic stack:
        - `saved_idx`: PB index of the JPF instruction (jump if false).
        - `cond_addr`: Address of the loop condition's result.
        - `jp_target`: PB index to jump to for beginning of loop (label).
        Generates an unconditional jump back to `jp_target`.
        Backpatches the JPF instruction at `saved_idx` to jump to end of loop (current pb_index).
        Also backpatches 'break' statements to jump to current pb_index.
        """
        try:
            saved_idx_for_jpf = self.semantic_stack.pop()    # Index of the (JPF, cond, TARGET_END)
            cond_addr = self._resolve_addr(self.semantic_stack.pop()) # Address of condition's result
            loop_start_label = self.semantic_stack.pop()     # Address to jump to for loop start

            # Unconditional jump back to the start of the loop's condition check
            self._add_three_addr_code(("jp", loop_start_label))

            # Backpatch the conditional jump: if condition is false, jump to instruction after the loop
            # (JPF, cond_addr, current_pb_index)
            self._add_three_addr_code(("jpf", cond_addr, MemoryManager.pb_index),
                                      idx=saved_idx_for_jpf, insert=True, increment=False)
        except IndexError:
            pass # Stack error

        # Backpatch any 'break' statements encountered within this loop
        try:
            self.cont_label_stack.pop() # Pop continue target for this loop
            break_locations = self.break_loc_stack.pop() # Get list of break placeholder indices
            for break_placeholder_idx in break_locations:
                # Make breaks jump to the instruction after the loop (current_pb_index)
                self._add_three_addr_code(("jp", MemoryManager.pb_index), 
                                           idx=break_placeholder_idx, insert=True, increment=False)
        except IndexError:
            pass # No breaks or continues in this loop
        

    def init_while_stacks_routine(self, input_token):
        """
        Initializes stacks for managing 'continue' and 'break' jumps within a 'while' loop.
        Pushes current `pb_index` (start of loop, target for 'continue') onto `cont_label_stack`.
        Pushes an empty list onto `break_loc_stack` to collect 'break' placeholder indices.
        """
        self.cont_label_stack.append(MemoryManager.pb_index) # 'continue' jumps here
        self.break_loc_stack.append([]) # To store indices of 'break' JPs


    def cont_jp_routine(self, input_token):
        """
        Generates an unconditional jump for a 'continue' statement.
        The jump target is the latest address on `cont_label_stack` (start of current loop).
        TAC: (JP, continue_target_addr)
        """
        self._add_three_addr_code(("jp", self.cont_label_stack[-1]))


    def break_jp_save_routine(self, input_token):
        """
        Handles a 'break' statement.
        Appends current `pb_index` to the list on top of `break_loc_stack`.
        Adds a placeholder TAC for the jump, to be backpatched when loop/switch ends.
        """
        self.break_loc_stack[-1].append(MemoryManager.pb_index) # Save placeholder index
        self._add_placeholder() # Placeholder for (JP, break_target_addr)


    def if_else_routine(self, input_token):
        """
        Backpatches the jump instruction for the 'else' part of an if-else statement.
        Pops `saved_idx` from semantic stack (this was the placeholder for JP after 'if' block).
        Fills it to jump to the current `pb_index` (instruction after 'else' block).
        TAC at saved_idx: (JP, current_pb_index)
        """
        try:
            saved_idx_after_if_block = self.semantic_stack.pop() # Index of (JP, TARGET_AFTER_ELSE)
            # Backpatch the jump from end of 'if' block to instruction after 'else' block
            self._add_three_addr_code(("jp", MemoryManager.pb_index), 
                                        idx=saved_idx_after_if_block, insert=True, increment=False)
        except IndexError:
            pass # Stack error


    def else_routine(self, input_token):
        """
        Handles the 'else' keyword in an if-else statement.
        Pops `saved_idx_for_jpf` (placeholder for JPF from 'if' condition) and `cond_addr`.
        Pushes current `pb_index` (start of 'else' block) onto stack (becomes `saved_idx_after_if_block` for `if_else_routine`).
        Adds a placeholder for the jump after the 'if' block.
        Backpatches the JPF from 'if' to jump to current `pb_index` (start of 'else' code).
        """
        try:
            saved_idx_for_jpf = self.semantic_stack.pop() # Index of (JPF, cond, TARGET_ELSE)
            cond_addr = self._resolve_addr(self.semantic_stack.pop()) # Condition of 'if'

            # This pb_index will be the target for the JP at the end of the 'if' block
            self.semantic_stack.append(MemoryManager.pb_index)
            self._add_placeholder() # Placeholder for (JP, TARGET_AFTER_ELSE)

            # Backpatch the JPF: if condition is false, jump to start of 'else' block (current_pb_index + 1, since placeholder was just added)
            # The placeholder is for the JP that skips the else block.
            # So, JPF target is current_pb_index (where else code starts, which is after the new placeholder).
            self._add_three_addr_code(("jpf", cond_addr, MemoryManager.pb_index),
                                        idx=saved_idx_for_jpf, insert=True, increment=False)
        except IndexError:
            pass # Stack error


    # ---                         END OF CODE GENERATION ROUTINES                      --- #


    def code_gen(self, action_symbol, input_token):
        if not SymbolTableManager.error_flag:
            try:
                self.semantic_routines[action_symbol](input_token)
            except Exception as e:
                print(f"Error in semantic routine {action_symbol}:", str(e))