"""Tests for the Phase 2 ARM interpreter. Instructions are hand-encoded."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "cpu"))
import arm_interp as A  # noqa: E402


def load(program, base=0, mem_size=0x1000):
    mem = A.Memory(mem_size, base=0)
    for i, word in enumerate(program):
        mem.write32(base + i * 4, word)
    return A.Arm(mem, pc=base)


class DataProcessingTests(unittest.TestCase):
    def test_mov_immediate(self):
        cpu = load([0xE3A00005])            # MOV r0, #5
        cpu.run(1)
        self.assertEqual(cpu.regs[0], 5)

    def test_add_immediate(self):
        cpu = load([0xE3A00005, 0xE2801003])  # MOV r0,#5 ; ADD r1,r0,#3
        cpu.run(2)
        self.assertEqual(cpu.regs[1], 8)

    def test_sub_register(self):
        cpu = load([0xE3A00005, 0xE3A01009, 0xE0412000])  # r0=5, r1=9, SUB r2,r1,r0
        cpu.run(3)
        self.assertEqual(cpu.regs[2], 4)

    def test_cmp_sets_zero_flag(self):
        cpu = load([0xE3A00005, 0xE3500005])  # MOV r0,#5 ; CMP r0,#5
        cpu.run(2)
        self.assertTrue(cpu.z)
        self.assertFalse(cpu.n)

    def test_sub_borrow_clears_carry(self):
        cpu = load([0xE3A00001, 0xE3500002])  # MOV r0,#1 ; CMP r0,#2 -> borrow
        cpu.run(2)
        self.assertFalse(cpu.c)
        self.assertTrue(cpu.n)

    def test_overflow_flag(self):
        cpu = load([
            0xE3E00102,  # MVN r0, #0x80000000 -> r0 = 0x7FFFFFFF
            0xE2901001,  # ADDS r1, r0, #1 -> signed overflow
        ])
        cpu.run(2)
        self.assertEqual(cpu.regs[0], 0x7FFFFFFF)
        self.assertEqual(cpu.regs[1], 0x80000000)
        self.assertTrue(cpu.v)
        self.assertTrue(cpu.n)

    def test_condition_skips_instruction(self):
        cpu = load([
            0xE3A00000,  # MOV r0, #0 -> Z is clear after a non-zero compare
            0xE3500001,  # CMP r0, #1
            0x03A00001,  # MOVEQ r0, #1  (skipped because Z is clear)
        ])
        cpu.run(3)
        self.assertEqual(cpu.regs[0], 0)


class BranchTests(unittest.TestCase):
    def test_branch_forward(self):
        cpu = load([0xEA000002, 0xE3A00001, 0xE3A00002, 0xE3A00003])  # B +8 skips two MOVs
        cpu.run(1)
        self.assertEqual(cpu.pc, 0x10)

    def test_bl_sets_link_register(self):
        cpu = load([0xEB000002, 0xE3A00001, 0xE3A00002, 0xE3A00003])  # BL +8
        cpu.run(1)
        self.assertEqual(cpu.regs[14], 4)
        self.assertEqual(cpu.pc, 0x10)

    def test_countdown_loop(self):
        # 0: SUB r0,r0,#1 ; 4: CMP r0,#0 ; 8: BNE 0
        cpu = load([0xE2400001, 0xE3500000, 0x1AFFFFFC])
        cpu.regs[0] = 5
        executed = cpu.run(1000, stop_pc=12)
        self.assertEqual(cpu.regs[0], 0)
        self.assertEqual(cpu.pc, 12)
        self.assertEqual(executed, 15)  # 5 iterations of 3 instructions


class MemoryTests(unittest.TestCase):
    def test_store_then_load(self):
        cpu = load([
            0xE3A00042,  # MOV r0, #0x42
            0xE3A03C01,  # MOV r3, #0x100
            0xE5830004,  # STR r0, [r3, #4]
            0xE5934004,  # LDR r4, [r3, #4]
        ])
        cpu.run(4)
        self.assertEqual(cpu.regs[4], 0x42)
        self.assertEqual(cpu.mem.read32(0x104), 0x42)

    def test_unaligned_access_raises(self):
        cpu = load([0xE3A03002, 0xE5930000])  # MOV r3,#2 ; LDR r0,[r3]
        with self.assertRaises(A.CpuError):
            cpu.run(2)


class UnsupportedTests(unittest.TestCase):
    def test_bkpt_error_message(self):
        cpu = load([0xE1200070])
        with self.assertRaisesRegex(A.CpuError, "BKPT"):
            cpu.step()

    def test_unsupported_instruction_raises(self):
        cpu = load([0xE1200070])  # BKPT, not implemented
        with self.assertRaises(A.CpuError):
            cpu.step()

    def test_unsupported_shift_raises(self):
        cpu = load([0xE1A00120])  # MOV r0, r0, LSR #0 style shift (shift type 01), not implemented
        with self.assertRaises(A.CpuError):
            cpu.step()


class BxTests(unittest.TestCase):
    def test_bx_to_thumb(self):
        cpu = load([0xE3A00011, 0xE12FFF10])  # MOV r0,#0x11 ; BX r0
        cpu.mem.write32(0x10, 0)              # placeholder, overwritten below
        cpu.mem.data[0x10:0x12] = (0x2107).to_bytes(2, "little")  # Thumb MOV r1,#7
        cpu.run(3)
        self.assertTrue(cpu.thumb)
        self.assertEqual(cpu.pc, 0x12)
        self.assertEqual(cpu.regs[1], 7)

    def test_bx_to_arm(self):
        cpu = load([0xE3A00020, 0xE12FFF10, 0xE3A01009])  # MOV r0,#0x20 ; BX r0 ; MOV r1,#9
        cpu.run(2)
        self.assertFalse(cpu.thumb)
        self.assertEqual(cpu.pc, 0x20)


def load_thumb(halfwords, base=0, mem_size=0x1000):
    mem = A.Memory(mem_size, base=0)
    for i, hw in enumerate(halfwords):
        mem.data[base + i * 2:base + i * 2 + 2] = hw.to_bytes(2, "little")
    return A.Arm(mem, pc=base, thumb=True)


class ThumbTests(unittest.TestCase):
    def test_mov_cmp_add_sub_immediate(self):
        cpu = load_thumb([0x2005, 0x3103, 0x2805, 0x3801])  # MOV r0,#5 ; ADD r1,#3 ; CMP r0,#5 ; SUB r0,#1
        cpu.run(3)
        self.assertEqual(cpu.regs[0], 5)
        self.assertEqual(cpu.regs[1], 3)
        self.assertTrue(cpu.z)
        cpu.run(1)
        self.assertEqual(cpu.regs[0], 4)

    def test_add_register(self):
        cpu = load_thumb([0x2005, 0x2103, 0x1842])  # r0=5 ; r1=3 ; ADD r2,r0,r1
        cpu.run(3)
        self.assertEqual(cpu.regs[2], 8)

    def test_bx_lr_returns(self):
        cpu = load_thumb([0x4770])  # BX lr
        cpu.regs[14] = 0x21         # thumb address
        cpu.run(1)
        self.assertEqual(cpu.pc, 0x20)
        self.assertTrue(cpu.thumb)

    def test_countdown_loop(self):
        # 0: SUB r0,#1 ; 2: CMP r0,#0 ; 4: BNE 0
        cpu = load_thumb([0x3801, 0x2800, 0xD1FC])
        cpu.regs[0] = 5
        executed = cpu.run(1000, stop_pc=6)
        self.assertEqual(cpu.regs[0], 0)
        self.assertEqual(cpu.pc, 6)
        self.assertEqual(executed, 15)

    def test_unconditional_branch(self):
        cpu = load_thumb([0xE001, 0x2001, 0x2002, 0x2003])  # B +4 skips one halfword
        cpu.run(1)
        self.assertEqual(cpu.pc, 6)

    def test_bl_sets_link_and_jumps(self):
        cpu = load_thumb([0xF000, 0xF806])  # BL to 0x10
        cpu.run(1)
        self.assertEqual(cpu.pc, 0x10)
        self.assertEqual(cpu.regs[14], 5)   # return address 4, Thumb bit set

    def test_ldr_pc_relative(self):
        cpu = load_thumb([0x4801])          # LDR r0,[pc,#4] -> address 8
        cpu.mem.write32(8, 0x12345678)
        cpu.run(1)
        self.assertEqual(cpu.regs[0], 0x12345678)

    def test_word_store_then_load(self):
        # MOV r0,#0x42 ; STR r0,[r3,#4] ; LDR r4,[r3,#4]  (r3 set by the test)
        cpu = load_thumb([0x2042, 0x6058, 0x685C])  # STR/LDR use word offset 1 (4 bytes)
        cpu.regs[3] = 0x100
        cpu.run(3)
        self.assertEqual(cpu.mem.read32(0x104), 0x42)
        self.assertEqual(cpu.regs[4], 0x42)

    def test_unsupported_thumb_raises(self):
        cpu = load_thumb([0x0000 | (0b00000 << 11) | (1 << 6)])  # LSL-style shift, not implemented
        with self.assertRaises(A.CpuError):
            cpu.step()


if __name__ == "__main__":
    unittest.main()
