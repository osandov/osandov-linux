/*
 * Hacky kernel module that overwrites the BPF verifier code so that all
 * programs pass. This is a really bad idea, but it can be useful.
 */

#include <linux/kallsyms.h>
#include <linux/memory.h>
#include <linux/module.h>
#include <asm/text-patching.h>

#ifdef CONFIG_X86_64
static const char return_0[] = {
	0x48, 0x31, 0xc0,	/* xorq %rax, %rax */
	0xc3,			/* retq */
};
#else
#error unsupported architecture
#endif

static char old_text[sizeof(return_0)];

static unsigned long text_poke_fallback;
module_param_named(text_poke, text_poke_fallback, ulong, S_IRUGO);
MODULE_PARM_DESC(text_poke, "address of text_poke symbol to use if kallsyms lookup fails");

static unsigned long text_mutex_fallback;
module_param_named(text_mutex, text_mutex_fallback, ulong, S_IRUGO);
MODULE_PARM_DESC(text_mutex, "address of text_mutex symbol to use if kallsyms lookup fails");

static unsigned long bpf_check_fallback;
module_param_named(bpf_check, bpf_check_fallback, ulong, S_IRUGO);
MODULE_PARM_DESC(bpf_check, "address of bpf_check symbol to use if kallsyms lookup fails");

/*
 * These symbols are not exported, but we can hack around that with kallsyms. If
 * that fails, the user can give us the address from System.map.
 */
static typeof(text_poke) *__text_poke;
static typeof(text_mutex) *__text_mutex;
static void *__bpf_check;

static void *lookup_sym_or_fallback(const char *name, unsigned long fallback)
{
	unsigned long addr;

	addr = kallsyms_lookup_name(name);
	if (!addr && !(addr = fallback)) {
		pr_err("bpfnocheck: kallsyms_lookup_name(\"%s\") failed\n", name);
		pr_err("bpfnocheck: try passing %s=\"$(awk '$3 == \"%s\" { print \"0x\" $1 }' System.map)\"\n", name, name);
	}
	return (void *)addr;
}

static int __init bpfnocheck_init(void)
{
	__text_poke = lookup_sym_or_fallback("text_poke", text_poke_fallback);
	if (!__text_poke)
		return -ENOENT;

	__text_mutex = lookup_sym_or_fallback("text_mutex", text_mutex_fallback);
	if (!__text_mutex)
		return -ENOENT;

	__bpf_check = lookup_sym_or_fallback("bpf_check", bpf_check_fallback);
	if (!__bpf_check)
		return -ENOENT;

	mutex_lock(__text_mutex);
	memcpy(old_text, __bpf_check, sizeof(old_text));
	(*__text_poke)(__bpf_check, return_0, sizeof(return_0));
	mutex_unlock(__text_mutex);
	return 0;
}

static void __exit bpfnocheck_exit(void)
{
	mutex_lock(__text_mutex);
	(*__text_poke)(__bpf_check, old_text, sizeof(old_text));
	mutex_unlock(__text_mutex);
}

module_init(bpfnocheck_init);
module_exit(bpfnocheck_exit);

MODULE_AUTHOR("Omar Sandoval <osandov@osandov.com>");
MODULE_DESCRIPTION("Disables the BPF verifier");
MODULE_LICENSE("GPL");
