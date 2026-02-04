import os
import subprocess
import csv

# =============== =====================

class Uad():
    def __init__(self, inst):
        self.inst = inst

    def reset(self):
        os.system(f'{self.inst}.exe com --action reset')

    def enable(self):
        os.system(f'{self.inst}.exe com --action enable')

    def disable(self):
        os.system(f'{self.inst}.exe com --action disable')

    def halt(self):
        csr = self.read_CSR()
        if csr is not None:
            csr |= (1 << 5)   # HALT
            csr |= (1 << 17)  # IBCLR
            csr |= (1 << 18)  # TCLR
            self.write_CSR(csr)

    def run(self):
        csr = self.read_CSR()
        if csr is not None:
            csr &= ~(1 << 5)  # HALT = 0
            csr |= 1          # FEN = 1
            self.write_CSR(csr)

    def read_CSR(self):
        try:
            output = os.popen(f'{self.inst}.exe cfg --address 0x0').read().strip()
            return int(output, 16)
        except:
            return None

    def write_CSR(self, value):
        os.system(f'{self.inst}.exe cfg --address 0x0 --data {hex(value)}')

    def read_COEF(self):
        try:
            output = os.popen(f'{self.inst}.exe cfg --address 0x4').read().strip()
            return int(output, 16)
        except:
            return None

    def write_COEF(self, value):
        os.system(f'{self.inst}.exe cfg --address 0x4 --data {hex(value)}')

    def write_signal(self, data):
        output = os.popen(f'{self.inst}.exe sig --data {hex(data)}').read().strip()
        return int(output, 16) if output else None


def configure_coefficients(inst, config):
    test = Uad(inst)
    csr = test.read_CSR()
    coef_reg = 0

    for item in config:
        coef_num = item['coef']
        coef_value = item['value']
        en_value = item['en']

        coef_reg |= (coef_value << (coef_num * 8))

        if en_value == 1:
            csr |= (1 << (coef_num + 1))
        else:
            csr &= ~(1 << (coef_num + 1))

    test.write_COEF(coef_reg)
    test.write_CSR(csr)


def drive_input_signals(inst, vector_file):
    test = Uad(inst)
    outputs = []

    with open(vector_file, 'r') as file:
        for line in file:
            val = int(line.strip(), 16)
            out = test.write_signal(val)
            outputs.append(out)

    return outputs

# ==================== =====================

INSTANCES = ["golden", "impl0", "impl1", "impl2", "impl3", "impl4", "impl5"]
CFG_FILES = ["p0.cfg", "p4.cfg", "p7.cfg", "p9.cfg"]
VEC_FILE = "sqr.vec"
POR_FILE = "por.csv"

def load_cfg(file):
    cfg = []
    with open(file, 'r') as f:
        next(f)
        for line in f:
            c, e, v = line.strip().split(',')
            cfg.append({'coef': int(c), 'en': int(e), 'value': int(v, 16)})
    return cfg


def tc1_global_enable():
    print("\n=== TC1: GLOBAL ENABLE / DISABLE ===")
    for inst in INSTANCES:
        u = Uad(inst)
        u.reset()
        u.disable()

        csr = u.read_CSR()

        if csr is None:
            # This is EXPECTED behavior
            print(f"{inst}: interface unavailable when disabled → PASS")
        else:
            fen = csr & 0x1
            status = "PASS" if fen == 0 else "FAIL"
            print(f"{inst}: CSR readable, FEN={fen} → {status}")



# ---------------- TC2 ----------------
def tc2_por():
    print("\n=== TC2: POR REGISTER VALUES ===")
    for inst in INSTANCES:
        u = Uad(inst)
        u.reset()
        u.enable()   # registers must be readable

        fail = False

        with open(POR_FILE, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                reg = row['register']
                field = row['field']
                expected = int(row['value'], 16)

                if reg == 'csr':
                    val = u.read_CSR()
                elif reg == 'coef':
                    val = u.read_COEF()
                else:
                    continue

                if val is None:
                    print(f"{inst}: cannot read {reg} → FAIL")
                    fail = True
                    continue

                # Extract field by name (manual mapping)
                if field == 'fen':
                    actual = (val >> 0) & 0x1
                elif field == 'c0en':
                    actual = (val >> 1) & 0x1
                elif field == 'c1en':
                    actual = (val >> 2) & 0x1
                elif field == 'c2en':
                    actual = (val >> 3) & 0x1
                elif field == 'c3en':
                    actual = (val >> 4) & 0x1
                elif field == 'halt':
                    actual = (val >> 5) & 0x1
                elif field == 'ibcnt':
                    actual = (val >> 8) & 0xFF
                elif field == 'ibovf':
                    actual = (val >> 16) & 0x1
                elif field == 'c0':
                    actual = (val >> 0) & 0xFF
                elif field == 'c1':
                    actual = (val >> 8) & 0xFF
                elif field == 'c2':
                    actual = (val >> 16) & 0xFF
                elif field == 'c3':
                    actual = (val >> 24) & 0xFF
                else:
                    continue

                if actual != expected:
                    print(f"{inst}: {reg}.{field} mismatch "
                          f"(exp={hex(expected)}, got={hex(actual)})")
                    fail = True

        print(f"{inst}: {'PASS' if not fail else 'FAIL'}")




# ---------------- TC3 ----------------
def tc3_input_buffer():
    print("\n=== TestCase3: INPUT BUFFER OVERFLOW ===")
    for inst in INSTANCES:
        u = Uad(inst)
        u.reset()
        u.enable()

        for _ in range(300):
            u.write_signal(0x10)

        csr = u.read_CSR()
        ibcnt = (csr >> 8) & 0xFF
        ibovf = (csr >> 16) & 0x1

        status = "PASS" if ibcnt == 255 and ibovf == 1 else "FAIL"
        print(f"{inst}: IBCNT={ibcnt}, IBOVF={ibovf} → {status}")


# ---------------- TC4 ----------------
def tc4_bypass():
    print("\n=== TC4: FILTER BYPASS ===")
    ref = None

    for inst in INSTANCES:
        u = Uad(inst)
        u.reset()
        u.enable()
        out = drive_input_signals(inst, VEC_FILE)

        if inst == "golden":
            ref = out
        else:
            print(f"{inst}: {'PASS' if out == ref else 'FAIL'}")


# ---------------- TC5 ----------------
def tc5_signal_processing():
    print("\n=== TC5: SIGNAL PROCESSING ===")

    for cfg_file in CFG_FILES:
        print(f"\n--- Using {cfg_file} ---")
        cfg = load_cfg(cfg_file)
        golden_out = None

        for inst in INSTANCES:
            u = Uad(inst)
            u.reset()
            u.enable()
            u.halt()
            configure_coefficients(inst, cfg)
            u.run()
            out = drive_input_signals(inst, VEC_FILE)

            if inst == "golden":
                golden_out = out
            else:
                print(f"{inst}: {'PASS' if out == golden_out else 'FAIL'}")


if __name__ == "__main__":
    tc1_global_enable()
    tc2_por()
    tc3_input_buffer()
    tc4_bypass()
    tc5_signal_processing()

    print("\n=== FINAL PROJECT COMPLETE ===")