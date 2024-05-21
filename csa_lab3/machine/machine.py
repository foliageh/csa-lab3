import logging
import sys
from enum import Enum

from .isa import JUMP_INSTRUCTIONS, AddressingMode, Instruction, Opcode, binary2machine


class ALUMode(Enum):
    UNARY_LEFT = 0
    UNARY_RIGHT = 1
    BINARY = 2


class DataPath:
    def __init__(self, memory: list[int], memory_capacity: int, input_buffer: str):
        assert 0 <= memory_capacity <= 2**31, 'Data memory can consist of a maximum of 2^31 cells'
        assert len(memory) < memory_capacity, 'Memory capacity exceeded'
        self.memory = memory + [0] * (memory_capacity - len(memory))
        self.memory_capacity = memory_capacity
        self.memory_output = 0

        self.acc = 0
        self.address_reg = 0

        self.alu_output = 0
        self._flag_zero = True
        self._flag_negative = False

        self.input_buffer = [char if char != '\n' else chr(0) for char in input_buffer] + [chr(0)]
        self.output_buffer = []

    def signal_latch_acc(self, sel_input: bool):
        if sel_input:
            if len(self.input_buffer) == 0:
                raise EOFError
            symbol = self.input_buffer.pop(0)
            logging.debug(f'input: {symbol!r}')
            self.acc = ord(symbol)
        else:
            self.acc = self.alu_output

    def signal_latch_address(self, sel_instr: bool, value: int | None = None):
        if sel_instr:
            self.address_reg = value
        else:
            self.address_reg = self.alu_output
        assert 0 <= self.address_reg < self.memory_capacity, f'Out of memory: {self.address_reg}'

    def alu_work(self, sel_instr: bool, mode: ALUMode, right: int | None = None, operation: Opcode | None = None):
        if not sel_instr:
            right = self.memory_output
        result = right if mode is ALUMode.UNARY_RIGHT else self.acc
        match operation:
            case Opcode.ADD:
                result += right
            case Opcode.SUB | Opcode.CMP:
                result -= right
            case Opcode.MUL:
                result *= right
            case Opcode.DIV:
                result //= right
            case Opcode.MOD:
                result %= right
        assert -(2**31) <= result <= 2**31 - 1, f'Integer overflow: {result}'
        self.alu_output = result

    def signal_read(self):
        self.memory_output = self.memory[self.address_reg]

    def signal_write(self):
        self.memory[self.address_reg] = self.alu_output

    def signal_output(self, is_number: bool = False):
        output = str(self.acc) if is_number else chr(self.acc)
        logging.debug(f'output: {"".join(self.output_buffer)!r} << {output!r}')
        self.output_buffer.append(str(output))

    def flag_zero(self) -> bool:
        return self.alu_output == 0

    def flag_negative(self) -> bool:
        return self.alu_output < 0


class ControlUnit:
    def __init__(self, instructions: list[Instruction], data_path: DataPath):
        self.instructions = instructions
        self.instr_pointer = 0
        self.data_path = data_path
        self._tick = 0

    def tick(self):
        self._tick += 1

    def current_tick(self):
        return self._tick

    def signal_latch_instr_pointer(self, sel_next: bool, instr_pointer: int | None = None):
        if sel_next:
            self.instr_pointer += 1
        else:
            self.instr_pointer = instr_pointer

    def decode_and_execute_control_flow_instruction(self, instr: Instruction):
        if instr.opcode is Opcode.HLT:
            raise StopIteration

        if instr.opcode not in JUMP_INSTRUCTIONS:
            return False

        sel_next = True
        match instr.opcode:
            case Opcode.JMP:
                sel_next = False
            case Opcode.JE:
                sel_next = not self.data_path.flag_zero()
            case Opcode.JNE:
                sel_next = self.data_path.flag_zero()
            case Opcode.JL:
                sel_next = not self.data_path.flag_negative()
            case Opcode.JG:
                sel_next = self.data_path.flag_negative() or self.data_path.flag_zero()
        self.signal_latch_instr_pointer(sel_next=sel_next, instr_pointer=instr.argument)
        self.tick()

        return True

    def decode_and_execute_instruction(self):
        instr = self.instructions[self.instr_pointer]

        if self.decode_and_execute_control_flow_instruction(instr):
            return

        if instr.opcode in {Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV, Opcode.MOD, Opcode.CMP}:
            if instr.addressing_mode is AddressingMode.IMMEDIATE:
                self.data_path.alu_work(sel_instr=True, mode=ALUMode.BINARY, right=instr.argument, operation=instr.opcode)
            else:
                self.data_path.signal_latch_address(sel_instr=True, value=instr.argument)
                self.data_path.signal_read()
                self.tick()
                self.data_path.alu_work(sel_instr=False, mode=ALUMode.BINARY, operation=instr.opcode)
            if instr.opcode is not Opcode.CMP:
                self.data_path.signal_latch_acc(sel_input=False)
        elif instr.opcode is Opcode.LD:
            if instr.addressing_mode is AddressingMode.IMMEDIATE:
                self.data_path.alu_work(sel_instr=True, mode=ALUMode.UNARY_RIGHT, right=instr.argument)
            else:
                self.data_path.signal_latch_address(sel_instr=True, value=instr.argument)
                self.data_path.signal_read()
                self.tick()
                self.data_path.alu_work(sel_instr=False, mode=ALUMode.UNARY_RIGHT)
                if instr.addressing_mode is AddressingMode.INDIRECT:
                    self.data_path.signal_latch_address(sel_instr=False)
                    self.data_path.signal_read()
                    self.tick()
                    self.data_path.alu_work(sel_instr=False, mode=ALUMode.UNARY_RIGHT)
            self.data_path.signal_latch_acc(sel_input=False)
        elif instr.opcode is Opcode.ST:
            self.data_path.signal_latch_address(sel_instr=True, value=instr.argument)
            if instr.addressing_mode is AddressingMode.INDIRECT:
                self.data_path.signal_read()
                self.tick()
                self.data_path.alu_work(sel_instr=False, mode=ALUMode.UNARY_RIGHT)
                self.data_path.signal_latch_address(sel_instr=False)
                self.tick()
            self.data_path.alu_work(sel_instr=False, mode=ALUMode.UNARY_LEFT)
            self.data_path.signal_write()
        elif instr.opcode is Opcode.IN:
            self.data_path.signal_latch_acc(sel_input=True)
            self.data_path.alu_work(sel_instr=False, mode=ALUMode.UNARY_LEFT)  # set flags
        elif instr.opcode in {Opcode.OUT, Opcode.OUTN}:
            self.data_path.signal_output(is_number=instr.opcode == Opcode.OUTN)
        self.tick()
        self.signal_latch_instr_pointer(sel_next=True)

    def __repr__(self):
        return (
            f'TICK: {self._tick:5} '
            f'IP: {self.instr_pointer:5} '
            f'ADDR: {self.data_path.address_reg:5} '
            f'MEM_OUT: {self.data_path.memory_output:5} '
            f'ALU_OUT: {self.data_path.alu_output:5} '
            f'ACC: {self.data_path.acc:5} '
            f'{self.instructions[self.instr_pointer]}'
        )


def simulation(instructions: list[Instruction], memory: list[int], input_stream: str,
               memory_capacity: int = 1000, instr_limit: int = 60000) -> tuple[str, int, int]:  # fmt: skip
    data_path = DataPath(memory, memory_capacity, input_stream)
    control_unit = ControlUnit(instructions, data_path)
    instr_counter = 0

    logging.debug(control_unit)
    try:
        while instr_counter < instr_limit:
            control_unit.decode_and_execute_instruction()
            instr_counter += 1
            if instr_counter < 500:
                logging.debug(control_unit)
            elif instr_counter == 500:
                logging.info('To see more than 500 executed instructions, purchase the paid version of the program!')
    except EOFError:
        logging.warning('Input buffer is empty!')
    except StopIteration:
        pass

    if instr_counter >= instr_limit:
        logging.warning('Instruction limit exceeded!')
    logging.info(f'output_buffer: {"".join(data_path.output_buffer)!r}')
    return ''.join(data_path.output_buffer), instr_counter, control_unit.current_tick()


def main(binary_file: str, input_file: str):
    instructions, memory = binary2machine(binary_file)
    with open(input_file, encoding='utf-8') as f:
        input_stream = f.read()

    output, instr_executed, ticks = simulation(instructions, memory, input_stream)

    print(f'output: {"".join(output)!r}')
    print('instr executed:', instr_executed)
    print('ticks:', ticks)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    assert len(sys.argv) == 3, 'Wrong arguments: machine.py <binary_file> <input_file>'
    _, binary_file, input_file = sys.argv
    main(binary_file, input_file)
