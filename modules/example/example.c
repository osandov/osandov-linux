#include <linux/module.h>

static int __init example_init(void)
{
	pr_info("Initializing example\n");
	return 0;
}

static void __exit example_exit(void)
{
	pr_info("Exiting example\n");
}

module_init(example_init);
module_exit(example_exit);

MODULE_LICENSE("GPL");
