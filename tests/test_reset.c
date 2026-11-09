/* Checks the generated header against the spec's reset values.
 *
 * Build and run (from the project root, after generating build/timer0.h):
 *     gcc -std=c11 -Wall -Wextra -Werror -Ibuild tests/test_reset.c -o build/test_reset
 *     build/test_reset
 * or just:  python tasks.py ctest
 *
 * Part 1 is generic: it walks every register and field through the header's
 * X-macro lists, so it keeps working when you add registers to the spec.
 * Part 2 holds hand-written "golden" values copied from spec/timer0.json.
 * They are deliberately independent of the generator: if a reset value
 * changes, this test fails until you update the value here on purpose.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "timer0.h"

static int checks, failures;

#define CHECK_EQ(actual, expected, what)                                        \
    do {                                                                        \
        uint32_t a_ = (uint32_t)(actual), e_ = (uint32_t)(expected);            \
        checks++;                                                               \
        if (a_ != e_) {                                                         \
            failures++;                                                         \
            printf("FAIL %-34s got 0x%08lX, expected 0x%08lX\n", (what),        \
                   (unsigned long)a_, (unsigned long)e_);                       \
        }                                                                       \
    } while (0)

#define CHECK(cond, what)                                                       \
    do {                                                                        \
        checks++;                                                               \
        if (!(cond)) {                                                          \
            failures++;                                                         \
            printf("FAIL %s\n", (what));                                        \
        }                                                                       \
    } while (0)

/* ----------------------------------------------------------------------------
 * A fake register block standing in for the hardware at TIMER0_BASE_ADDR.
 * Unused words are filled with junk so a layout mistake shows up as a wrong read.
 */
static uint32_t fake_mem[TIMER0_SIZE / sizeof(uint32_t)];

static void fake_reset(void)
{
    size_t i;
    for (i = 0; i < sizeof fake_mem / sizeof fake_mem[0]; i++)
        fake_mem[i] = 0xDEADBEEFu;
#define WRITE_RESET(name, offset, reset, access) fake_mem[(offset) / 4u] = (reset);
    TIMER0_REGISTER_LIST(WRITE_RESET)
#undef WRITE_RESET
}

/* One slot per register, so fields can be grouped by the register they belong to. */
enum {
#define REG_INDEX(name, offset, reset, access) REGIDX_##name,
    TIMER0_REGISTER_LIST(REG_INDEX)
#undef REG_INDEX
    NUM_REGS_
};

static void test_layout_and_reset(const TIMER0_Type *dev)
{
    char what[96];

    CHECK_EQ(NUM_REGS_, TIMER0_REG_COUNT, "register count");

#define CHECK_REG(name, offset, reset, access)                                  \
    snprintf(what, sizeof what, "%s offset aligned", #name);                    \
    CHECK((offset) % 4u == 0u, what);                                           \
    snprintf(what, sizeof what, "%s inside block", #name);                      \
    CHECK((offset) + 4u <= TIMER0_SIZE, what);                                  \
    snprintf(what, sizeof what, "%s struct offset", #name);                     \
    CHECK_EQ(offsetof(TIMER0_Type, name), (offset), what);                      \
    snprintf(what, sizeof what, "%s reset via struct", #name);                  \
    CHECK_EQ(dev->name, (reset), what);
    TIMER0_REGISTER_LIST(CHECK_REG)
#undef CHECK_REG
}

static void test_fields(void)
{
    static const uint32_t reg_reset[NUM_REGS_] = {
#define RESET_OF(name, offset, reset, access) [REGIDX_##name] = (reset),
        TIMER0_REGISTER_LIST(RESET_OF)
#undef RESET_OF
    };
    static const char *const reg_name[NUM_REGS_] = {
#define NAME_OF(name, offset, reset, access) [REGIDX_##name] = #name,
        TIMER0_REGISTER_LIST(NAME_OF)
#undef NAME_OF
    };
    uint32_t covered[NUM_REGS_] = {0};
    uint32_t rebuilt[NUM_REGS_] = {0};
    char what[96];
    int i;

#define CHECK_FIELD(reg, field)                                                 \
    {                                                                           \
        const uint32_t mask  = TIMER0_##reg##_##field##_MASK;                   \
        const uint32_t shift = TIMER0_##reg##_##field##_SHIFT;                  \
        const uint32_t width = TIMER0_##reg##_##field##_WIDTH;                  \
        const uint32_t fres  = TIMER0_##reg##_##field##_RESET;                  \
        /* 64-bit maths so a 32-bit wide field doesn't overflow the shift. */   \
        const uint64_t want  = ((((uint64_t)1 << width) - 1u) << shift);        \
        snprintf(what, sizeof what, "%s.%s fits in 32 bits", #reg, #field);     \
        CHECK(width >= 1u && shift + width <= 32u, what);                       \
        snprintf(what, sizeof what, "%s.%s mask matches shift/width", #reg, #field); \
        CHECK_EQ(mask, (uint32_t)want, what);                                   \
        snprintf(what, sizeof what, "%s.%s overlaps another field", #reg, #field); \
        CHECK((covered[REGIDX_##reg] & mask) == 0u, what);                      \
        covered[REGIDX_##reg] |= mask;                                          \
        snprintf(what, sizeof what, "%s.%s field reset", #reg, #field);         \
        CHECK_EQ(TIMER0_FIELD_GET(TIMER0_##reg##_RESET, mask, shift), fres, what); \
        rebuilt[REGIDX_##reg] |= TIMER0_FIELD_PREP(fres, mask, shift);          \
    }
    TIMER0_FIELD_LIST(CHECK_FIELD)
#undef CHECK_FIELD

    /* Putting every field's reset value back together must give the register reset. */
    for (i = 0; i < NUM_REGS_; i++) {
        snprintf(what, sizeof what, "%s rebuilt from fields", reg_name[i]);
        CHECK_EQ(rebuilt[i], reg_reset[i], what);
    }
}

/* ----------------------------------------------------------------------------
 * Golden values from spec/timer0.json. Update these when you change a
 * reset value in the spec on purpose.
 */
static void test_golden(const TIMER0_Type *dev)
{
    CHECK_EQ(TIMER0_BASE_ADDR, 0x40001000u, "TIMER0_BASE_ADDR");

    CHECK_EQ(dev->CTRL,       0x00000300u, "golden CTRL");
    CHECK_EQ(dev->STATUS,     0x00000001u, "golden STATUS");
    CHECK_EQ(dev->INT_STATUS, 0x00000000u, "golden INT_STATUS");
    CHECK_EQ(dev->COUNT,      0x00000000u, "golden COUNT");
    CHECK_EQ(dev->COMPARE,    0xFFFFFFFFu, "golden COMPARE");
    CHECK_EQ(dev->CMD,        0x00000000u, "golden CMD");
    CHECK_EQ(dev->ID,         0x7E1A0102u, "golden ID");

    CHECK_EQ(TIMER0_FIELD_GET(dev->CTRL, TIMER0_CTRL_PRESCALE_MASK, TIMER0_CTRL_PRESCALE_SHIFT),
             3u, "golden CTRL.PRESCALE");
    CHECK_EQ(TIMER0_FIELD_GET(dev->CTRL, TIMER0_CTRL_EN_MASK, TIMER0_CTRL_EN_SHIFT),
             0u, "golden CTRL.EN");
    CHECK_EQ(TIMER0_FIELD_GET(dev->STATUS, TIMER0_STATUS_READY_MASK, TIMER0_STATUS_READY_SHIFT),
             1u, "golden STATUS.READY");
    CHECK_EQ(TIMER0_FIELD_GET(dev->ID, TIMER0_ID_PART_MASK, TIMER0_ID_PART_SHIFT),
             0x7E1Au, "golden ID.PART");
    CHECK_EQ(TIMER0_FIELD_GET(dev->ID, TIMER0_ID_MAJOR_MASK, TIMER0_ID_MAJOR_SHIFT),
             0x01u, "golden ID.MAJOR");
    CHECK_EQ(TIMER0_FIELD_GET(dev->ID, TIMER0_ID_MINOR_MASK, TIMER0_ID_MINOR_SHIFT),
             0x02u, "golden ID.MINOR");
}

int main(void)
{
    const TIMER0_Type *dev = (const TIMER0_Type *)(void *)fake_mem;

    fake_reset();
    test_layout_and_reset(dev);
    test_fields();
    test_golden(dev);

    printf("%s: %d checks, %d failed\n", failures ? "FAILED" : "OK", checks, failures);
    return failures ? 1 : 0;
}
