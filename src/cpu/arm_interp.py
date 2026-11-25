"""Phase 2: interpreter for the 3DS ARM11 CPU (ARM and Thumb subsets).

ARM implemented: data processing (immediate, and register with LSL #imm),
B, BL, BX, LDR and STR with immediate offset, and condition codes.

Thumb implemented: MOV/CMP/ADD/SUB with immediate, ADD/SUB register and
immediate, ALU operations (AND, EOR, TST, NEG, CMP, CMN, ORR, BIC, MVN),
high-register ADD/CMP/MOV and BX, LDR PC-relative, word LDR/STR with
immediate offset, conditional and unconditional branches, and BL.

Not implemented: shifts other than LSL in ARM, multiply, halfword and block
transfers, byte transfers, coprocessor instructions, SWI, exceptions, and
the rest of the Thumb formats. Unsupported encodings raise CpuError rather
than being guessed.

Known simplification: logical operations do not update the C flag from the
shifter carry in every case. Fix before relying on exact flag behaviour.
"""
from typing import Optional

MASK = 0xFFFFFFFF


class CpuError(Exception):
    pass


def _ror(value: int, n: int) -> int:
    n %= 32
    return ((value >> n) | (value << (32 - n))) & MASK if n else value & MASK


def _sign(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


class Memory:
    def __init__(self, size: int, base: int = 0):
        self.base = base
        self.data = bytearray(size)

    def _off(self, addr: int, n: int) -> int:
        o = addr - self.base
        if o < 0 or o + n > len(self.data):
            raise CpuError(f"memory access out of range: {addr:#x}")
        return o

    def read16(self, addr: int) -> int:
        if addr & 1:
            raise CpuError(f"unaligned halfword read at {addr:#x}")
        o = self._off(addr, 2)
        return int.from_bytes(self.data[o:o + 2], "little")

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
    def __init__(self, mem: Memory, pc: int = 0, thumb: bool = False):
        self.mem = mem
        self.regs = [0] * 15  # r0-r14
        self.pc = pc & MASK
        self.thumb = thumb
        self.n = self.z = self.c = self.v = False

    # Reading r15 gives the current instruction address + 8 (ARM) or + 4 (Thumb).
    def _reg(self, n: int) -> int:
        if n == 15:
            return (self.pc + (4 if self.thumb else 8)) & MASK
        return self.regs[n]

    def _set_reg(self, n: int, value: int) -> Optional[int]:
        """Returns a new PC if the write targets r15, else None."""
        if n == 15:
            return value & ~(1 if self.thumb else 3) & MASK
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

    def _set_arith_flags(self, arith) -> None:
        self._set_nz(arith[0])
        self.c, self.v = arith[1], arith[2]

    # ------------------------------------------------------------ fetch loop

    def step(self) -> None:
        if self.thumb:
            self._thumb_step()
        else:
            self._arm_step()

    def _arm_step(self) -> None:
        instr = self.mem.read32(self.pc)
        cond = instr >> 28
        next_pc = (self.pc + 4) & MASK

        if not self._cond_ok(cond):
            self.pc = next_pc
            return

        if (instr & 0x0FFFFFF0) == 0x012FFF10:  # BX
            self.pc = self._bx(instr & 0xF)
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

    def _bx(self, rm: int) -> int:
        target = self._reg(rm)
        if target & 1:
            self.thumb = True
            return target & ~1 & MASK
        self.thumb = False
        return target & ~3 & MASK

    # ---------------------------------------------------------------- ARM

    def _branch(self, instr: int) -> int:
        offset = _sign(instr & 0xFFFFFF, 24) << 2
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
                raise CpuError("only LSL shifts are implemented in ARM mode")
            val = self._reg(rm)
            if amount:
                op2 = (val << amount) & MASK
                shifter_carry = bool((val >> (32 - amount)) & 1)
            else:
                op2 = val
                shifter_carry = self.c

        a = self._reg(rn)
        arith = None
        if opcode in (0x0, 0x8):      # AND, TST
            res = a & op2
        elif opcode in (0x1, 0x9):    # EOR, TEQ
            res = a ^ op2
        elif opcode == 0xC:           # ORR
            res = a | op2
        elif opcode == 0xE:           # BIC
            res = a & ~op2 & MASK
        elif opcode == 0xD:           # MOV
            res = op2
        elif opcode == 0xF:           # MVN
            res = ~op2 & MASK
        elif opcode in (0x2, 0xA):    # SUB, CMP
            arith = self._add(a, ~op2 & MASK, 1)
            res = arith[0]
        elif opcode == 0x3:           # RSB
            arith = self._add(~a & MASK, op2, 1)
            res = arith[0]
        elif opcode in (0x4, 0xB):    # ADD, CMN
            arith = self._add(a, op2, 0)
            res = arith[0]
        elif opcode == 0x5:           # ADC
            arith = self._add(a, op2, int(self.c))
            res = arith[0]
        elif opcode == 0x6:           # SBC
            arith = self._add(a, ~op2 & MASK, int(self.c))
            res = arith[0]
        elif opcode == 0x7:           # RSC
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
                self.c = shifter_carry

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

    # -------------------------------------------------------------- Thumb

    def _thumb_step(self) -> None:
        hw = self.mem.read16(self.pc)
        next_pc = (self.pc + 2) & MASK

        if (hw >> 11) == 0b11110:  # BL: two halfwords
            next_pc = self._thumb_bl(hw)
        elif (hw >> 11) == 0b00011:
            self._thumb_add_sub_reg_imm(hw)
        elif (hw >> 13) == 0b001:
            self._thumb_imm8(hw)
        elif (hw >> 10) == 0b010000:
            self._thumb_alu(hw)
        elif (hw >> 10) == 0b010001:
            next_pc = self._thumb_hi_reg(hw, next_pc)
        elif (hw >> 11) == 0b01001:
            self._thumb_ldr_pc(hw)
        elif (hw >> 13) == 0b011 and not (hw >> 12) & 1:
            self._thumb_word_transfer(hw)
        elif (hw >> 12) == 0b1101:
            cond = (hw >> 8) & 0xF
            if cond == 0xE or cond == 0xF:
                raise CpuError(f"unsupported Thumb instruction {hw:#06x}")
            if self._cond_ok(cond):
                next_pc = (self.pc + 4 + _sign(hw & 0xFF, 8) * 2) & MASK
        elif (hw >> 11) == 0b11100:
            off = _sign(hw & 0x7FF, 11) * 2
            next_pc = (self.pc + 4 + off) & MASK
        else:
            raise CpuError(f"unsupported Thumb instruction {hw:#06x}")

        self.pc = next_pc

    def _thumb_bl(self, hw: int) -> int:
        hw2 = self.mem.read16(self.pc + 2)
        if (hw2 >> 11) != 0b11111:
            raise CpuError(f"malformed Thumb BL at {self.pc:#x}")
        hi = _sign(hw & 0x7FF, 11) << 12
        lo = (hw2 & 0x7FF) << 1
        target = (self.pc + 4 + hi + lo) & MASK
        self.regs[14] = ((self.pc + 4) | 1) & MASK
        return target & ~1 & MASK

    def _thumb_add_sub_reg_imm(self, hw: int) -> None:
        imm_form = (hw >> 10) & 1
        sub = (hw >> 9) & 1
        operand = (hw >> 6) & 7 if imm_form else self.regs[(hw >> 6) & 7]
        rs = self.regs[(hw >> 3) & 7]
        rd = hw & 7
        if sub:
            arith = self._add(rs, ~operand & MASK, 1)
        else:
            arith = self._add(rs, operand, 0)
        self._set_arith_flags(arith)
        self.regs[rd] = arith[0]

    def _thumb_imm8(self, hw: int) -> None:
        op = (hw >> 11) & 3
        rd = (hw >> 8) & 7
        imm = hw & 0xFF
        a = self.regs[rd]
        if op == 0:      # MOV
            self._set_nz(imm)
            self.regs[rd] = imm
        elif op == 1:    # CMP
            self._set_arith_flags(self._add(a, ~imm & MASK, 1))
        elif op == 2:    # ADD
            arith = self._add(a, imm, 0)
            self._set_arith_flags(arith)
            self.regs[rd] = arith[0]
        else:            # SUB
            arith = self._add(a, ~imm & MASK, 1)
            self._set_arith_flags(arith)
            self.regs[rd] = arith[0]

    def _thumb_alu(self, hw: int) -> None:
        op = (hw >> 6) & 0xF
        rs = self.regs[(hw >> 3) & 7]
        rd_idx = hw & 7
        rd = self.regs[rd_idx]
        write = True
        if op == 0x0 or op == 0x8:       # AND, TST
            res = rd & rs
            write = op == 0x0
        elif op == 0x1:                  # EOR
            res = rd ^ rs
        elif op == 0xC:                  # ORR
            res = rd | rs
        elif op == 0xE:                  # BIC
            res = rd & ~rs & MASK
        elif op == 0xF:                  # MVN
            res = ~rs & MASK
        elif op == 0x9:                  # NEG (RSB #0)
            arith = self._add(~rs & MASK, 0, 1)
            self._set_arith_flags(arith)
            self.regs[rd_idx] = arith[0]
            return
        elif op == 0xA or op == 0xB:     # CMP, CMN
            arith = self._add(rd, ~rs & MASK, 1) if op == 0xA else self._add(rd, rs, 0)
            self._set_arith_flags(arith)
            return
        else:
            raise CpuError(f"unsupported Thumb ALU operation {op:#x}")
        self._set_nz(res)
        if write:
            self.regs[rd_idx] = res & MASK

    def _thumb_hi_reg(self, hw: int, next_pc: int) -> int:
        op = (hw >> 8) & 3
        h1 = (hw >> 7) & 1
        h2 = (hw >> 6) & 1
        rs = ((hw >> 3) & 7) | (h2 << 3)
        rd = (hw & 7) | (h1 << 3)
        if op == 0:      # ADD (no flags)
            res = (self._reg(rd) + self._reg(rs)) & MASK
            new_pc = self._set_reg(rd, res)
            return new_pc if new_pc is not None else next_pc
        if op == 1:      # CMP
            self._set_arith_flags(self._add(self._reg(rd), ~self._reg(rs) & MASK, 1))
            return next_pc
        if op == 2:      # MOV (no flags)
            new_pc = self._set_reg(rd, self._reg(rs))
            return new_pc if new_pc is not None else next_pc
        return self._bx(rs)  # op == 3: BX

    def _thumb_ldr_pc(self, hw: int) -> None:
        rd = (hw >> 8) & 7
        addr = ((self.pc + 4) & ~3) + (hw & 0xFF) * 4
        self.regs[rd] = self.mem.read32(addr)

    def _thumb_word_transfer(self, hw: int) -> None:
        load = (hw >> 11) & 1
        offset = ((hw >> 6) & 0x1F) * 4
        rb = (hw >> 3) & 7
        rd = hw & 7
        addr = (self.regs[rb] + offset) & MASK
        if load:
            self.regs[rd] = self.mem.read32(addr)
        else:
            self.mem.write32(addr, self.regs[rd])

    # ----------------------------------------------------------- run loop

    def run(self, max_steps: int, stop_pc: Optional[int] = None) -> int:
        """Runs up to max_steps instructions. Returns how many ran."""
        for i in range(max_steps):
            if stop_pc is not None and self.pc == stop_pc:
                return i
            self.step()
        return max_steps
