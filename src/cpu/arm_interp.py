"""Phase 2: minimal ARM (32-bit) interpreter for the 3DS ARM11 CPU.

Implemented: a subset of ARM data processing (immediate, and register with
LSL #imm), B and BL, LDR and STR with immediate offset, and condition codes.

Not implemented yet: Thumb mode, BX, multiply, halfword and block transfers,
coprocessor instructions, shifts other than LSL, and exceptions. Unsupported
instructions raise CpuError rather than being guessed.
"""
from typing import Optional

MASK = 0xFFFFFFFF


class CpuError(Exception):
    pass


def _ror(value: int, n: int) -> int:
    n %= 32
    return ((value >> n) | (value << (32 - n))) & MASK if n else value & MASK


def _sign24(v: int) -> int:
    return v - 0x1000000 if v & 0x800000 else v


class Memory:
    def __init__(self, size: int, base: int = 0):
        self.base = base
        self.data = bytearray(size)

    def _off(self, addr: int, n: int) -> int:
        o = addr - self.base
        if o < 0 or o + n > len(self.data):
            raise CpuError(f"memory access out of range: {addr:#x}")
        return o

    def read32(self, addr: int) -> int:
        if addr & 3:
            raise CpuError(f"unaligned word read at {addr:#x}")
        o = self._off(addr, 4)
        return int.from_bytes(self.data[o:o + 4], "little")

    def write32(self, addr: int, value: int) -> None:
        if addr & 3:
            raise CpuError(f"unaligned word write at {addr:#x}")
        o = self._off(addr, 4)
        self.data[o:o + 4] = (value & MASK).to_bytes(4, "little")


class Arm:
    def __init__(self, mem: Memory, pc: int = 0):
        self.mem = mem
        self.regs = [0] * 15  # r0-r14
        self.pc = pc & MASK
        self.n = self.z = self.c = self.v = False

    # Reading r15 gives the address of the current instruction + 8.
    def _reg(self, n: int) -> int:
        if n == 15:
            return (self.pc + 8) & MASK
        return self.regs[n]

    def _set_reg(self, n: int, value: int) -> Optional[int]:
        """Returns a new PC if the write targets r15, else None."""
        if n == 15:
            return value & ~3 & MASK
        self.regs[n] = value & MASK
        return None

    def _cond_ok(self, cond: int) -> bool:
        table = {
            0x0: self.z,
            0x1: not self.z,
            0x2: self.c,
            0x3: not self.c,
            0x4: self.n,
            0x5: not self.n,
            0x6: self.v,
            0x7: not self.v,
            0x8: self.c and not self.z,
            0x9: (not self.c) or self.z,
            0xA: self.n == self.v,
            0xB: self.n != self.v,
            0xC: (not self.z) and (self.n == self.v),
            0xD: self.z or (self.n != self.v),
            0xE: True,
        }
        if cond not in table:
            raise CpuError(f"unsupported condition {cond:#x}")
        return table[cond]

    def _add(self, a: int, b: int, carry_in: int):
        total = a + b + carry_in
        res = total & MASK
        carry = (total >> 32) & 1
        overflow = bool(((~(a ^ b)) & (a ^ res)) & 0x80000000)
        return res, bool(carry), overflow

    def _set_nz(self, res: int) -> None:
        self.n = bool(res & 0x80000000)
        self.z = res == 0

    def step(self) -> None:
        instr = self.mem.read32(self.pc)
        cond = instr >> 28
        next_pc = (self.pc + 4) & MASK

        if not self._cond_ok(cond):
            self.pc = next_pc
            return

        if (instr & 0x0FF000F0) == 0x01200070:
            raise CpuError(f"BKPT is not implemented ({instr:#010x})")

        top = (instr >> 25) & 7
        if top == 0b101:
            next_pc = self._branch(instr)
        elif top in (0b000, 0b001):
            if top == 0 and (instr & 0x90) == 0x90:
                raise CpuError(f"unsupported instruction {instr:#010x} (multiply/halfword)")
            next_pc = self._data_processing(instr, next_pc)
        elif top == 0b010 and not (instr >> 25) & 1:
            next_pc = self._single_transfer(instr, next_pc)
        else:
            raise CpuError(f"unsupported instruction {instr:#010x}")

        self.pc = next_pc

    def _branch(self, instr: int) -> int:
        offset = _sign24(instr & 0xFFFFFF) << 2
        target = (self.pc + 8 + offset) & MASK
        if (instr >> 24) & 1:  # BL
            self.regs[14] = (self.pc + 4) & MASK
        return target

    def _data_processing(self, instr: int, next_pc: int) -> int:
        imm_form = bool((instr >> 25) & 1)
        opcode = (instr >> 21) & 0xF
        s = bool((instr >> 20) & 1)
        rn = (instr >> 16) & 0xF
        rd = (instr >> 12) & 0xF

        if imm_form:
            rot = ((instr >> 8) & 0xF) * 2
            op2 = _ror(instr & 0xFF, rot)
            shifter_carry = bool(op2 >> 31) if rot else self.c
        else:
            rm = instr & 0xF
            shift_type = (instr >> 5) & 3
            amount = (instr >> 7) & 0x1F
            if shift_type != 0:
                raise CpuError("only LSL shifts are implemented")
            val = self._reg(rm)
            if amount:
                op2 = (val << amount) & MASK
                shifter_carry = bool((val >> (32 - amount)) & 1)
            else:
                op2 = val
                shifter_carry = self.c

        a = self._reg(rn)
        arith = None  # (result, carry, overflow) for arithmetic ops
        if opcode == 0x0 or opcode == 0x8:      # AND, TST
            res = a & op2
        elif opcode == 0x1 or opcode == 0x9:    # EOR, TEQ
            res = a ^ op2
        elif opcode == 0xC:                     # ORR
            res = a | op2
        elif opcode == 0xE:                     # BIC
            res = a & ~op2 & MASK
        elif opcode == 0xD:                     # MOV
            res = op2
        elif opcode == 0xF:                     # MVN
            res = ~op2 & MASK
        elif opcode == 0x2 or opcode == 0xA:    # SUB, CMP
            arith = self._add(a, ~op2 & MASK, 1)
            res = arith[0]
        elif opcode == 0x3:                     # RSB
            arith = self._add(~a & MASK, op2, 1)
            res = arith[0]
        elif opcode == 0x4 or opcode == 0xB:    # ADD, CMN
            arith = self._add(a, op2, 0)
            res = arith[0]
        elif opcode == 0x5:                     # ADC
            arith = self._add(a, op2, int(self.c))
            res = arith[0]
        elif opcode == 0x6:                     # SBC
            arith = self._add(a, ~op2 & MASK, int(self.c))
            res = arith[0]
        elif opcode == 0x7:                     # RSC
            arith = self._add(~a & MASK, op2, int(self.c))
            res = arith[0]
        else:
            raise CpuError(f"unsupported data-processing opcode {opcode:#x}")

        test_only = opcode in (0x8, 0x9, 0xA, 0xB)
        if s or test_only:
            self._set_nz(res)
            if arith is not None:
                self.c, self.v = arith[1], arith[2]
            else:
                self.c = shifter_carry  # V unchanged for logical ops

        if test_only:
            return next_pc

        new_pc = self._set_reg(rd, res)
        return new_pc if new_pc is not None else next_pc

    def _single_transfer(self, instr: int, next_pc: int) -> int:
        pre = (instr >> 24) & 1
        up = (instr >> 23) & 1
        byte = (instr >> 22) & 1
        writeback = (instr >> 21) & 1
        load = (instr >> 20) & 1
        if not pre or writeback or byte:
            raise CpuError("only pre-indexed word LDR/STR without writeback are implemented")
        rn = (instr >> 16) & 0xF
        rd = (instr >> 12) & 0xF
        offset = instr & 0xFFF
        base = self._reg(rn)
        addr = (base + offset if up else base - offset) & MASK

        if load:
            new_pc = self._set_reg(rd, self.mem.read32(addr))
            return new_pc if new_pc is not None else next_pc
        self.mem.write32(addr, self._reg(rd))
        return next_pc

    def run(self, max_steps: int, stop_pc: Optional[int] = None) -> int:
        """Runs up to max_steps instructions. Returns how many ran."""
        for i in range(max_steps):
            if stop_pc is not None and self.pc == stop_pc:
                return i
            self.step()
        return max_steps
