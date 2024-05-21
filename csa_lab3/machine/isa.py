import struct
from enum import Enum
from typing import NamedTuple


class Opcode(Enum):
    HLT = 1
    # NOT = 2
    # INC = 3

    LD = 4
    ST = 5
    ADD = 6
    SUB = 7
    MUL = 8
    DIV = 9
    MOD = 10
    # AND = 11
    # OR = 12
    CMP = 13

    JMP = 14
    JE = 15
    JNE = 16
    JL = 17
    JG = 18

    IN = 19
    OUT = 20
    OUTN = 21


ZERO_ADDRESS_INSTRUCTIONS = {Opcode.HLT}
ADDRESS_INSTRUCTIONS = {Opcode.LD, Opcode.ST, Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV, Opcode.MOD, Opcode.CMP}
JUMP_INSTRUCTIONS = {Opcode.JMP, Opcode.JE, Opcode.JNE, Opcode.JL, Opcode.JG}
IO_INSTRUCTIONS = {Opcode.IN, Opcode.OUT, Opcode.OUTN}


class AddressingMode(Enum):
    DIRECT = 0
    INDIRECT = 1
    IMMEDIATE = 2


class Instruction(NamedTuple):
    opcode: Opcode
    argument: int = 0
    addressing_mode: AddressingMode = AddressingMode.DIRECT

    def __repr__(self):
        if self.opcode in ZERO_ADDRESS_INSTRUCTIONS:
            return self.opcode.name
        if self.opcode in ADDRESS_INSTRUCTIONS:
            return f'{self.opcode.name} {['', '~', '#'][self.addressing_mode.value]}{self.argument}'
        return f'{self.opcode.name} {self.argument}'


def machine2binary(instructions: list[Instruction], memory: list[int]) -> bytes:
    binary = b''
    for instr in instructions:
        op, addr_mode, arg = instr.opcode.value, instr.addressing_mode.value, instr.argument
        binary += struct.pack('>Bi', (op << 2) | addr_mode, arg)
    binary += b'\x00' * 5
    for value in memory:
        binary += struct.pack('>i', value)
    return binary


def binary2machine(binary_file: str) -> tuple[list[Instruction], list[int]]:
    instructions = []
    memory = []
    with open(binary_file, 'rb') as file:
        while instr := file.read(5):
            assert len(instr) == 5, 'The bytecode is invalid'
            if instr == b'\x00' * 5:
                break
            op, arg = struct.unpack('>Bi', instr)
            op, addr_mode = op >> 2, op & 0b11
            instructions.append(Instruction(Opcode(op), arg, AddressingMode(addr_mode)))
        while memory_word := file.read(4):
            assert len(memory_word) == 4, 'The bytecode is invalid'
            memory.append(struct.unpack('>i', memory_word)[0])
    return instructions, memory
