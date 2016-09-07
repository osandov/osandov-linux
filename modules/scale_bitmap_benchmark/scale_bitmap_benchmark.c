#include <linux/kthread.h>
#include <linux/module.h>
#include <linux/scale_bitmap.h>

static unsigned int depth = 128;
module_param(depth, uint, S_IRUGO);
MODULE_PARM_DESC(depth, "Bitmap depth");

static int shift = -1;
module_param(shift, int, S_IRUGO);
MODULE_PARM_DESC(shift, "log2(number of bits used per word) (int)");

static bool round_robin = false;
module_param(round_robin, bool, S_IRUGO);
MODULE_PARM_DESC(round_robin, "Allocate bits in strict round-robin order");

static int home_node = NUMA_NO_NODE;
module_param(home_node, int, S_IRUGO);
MODULE_PARM_DESC(home_node, "NUMA node to allocate bitmap queue on");

static struct task_struct **kthreads;
static struct scale_bitmap_queue *sbq;

static int scale_bitmap_perf_thread(void *data)
{
	ktime_t start, end;
	s64 delta;
	int i, nr;
	int cpu;

	cpu = get_cpu();

	start = ktime_get();
	for (i = 0; i < 1000000; i++) {
		nr = __scale_bitmap_queue_get(sbq);
		if (nr >= 0)
			scale_bitmap_queue_clear(sbq, nr, cpu);
	}
	end = ktime_get();
	delta = ktime_to_ns(ktime_sub(end, start));
	pr_info("CPU %d took %lld.%.9lld s\n", cpu,
		delta / NSEC_PER_SEC, delta % NSEC_PER_SEC);

	put_cpu();

	while (!kthread_should_stop()) {
		__set_current_state(TASK_INTERRUPTIBLE);
		schedule();
	}

	return 0;
}

static int __init scale_bitmap_perf_init(void)
{
	ktime_t start, end;
	s64 delta;
	struct task_struct *kthread;
	int cpu;
	int ret;

	sbq = kzalloc_node(sizeof(*sbq), GFP_KERNEL, home_node);
	if (!sbq)
		return -ENOMEM;

	ret = scale_bitmap_queue_init_node(sbq, depth, shift, round_robin,
					   GFP_KERNEL, home_node);
	if (ret)
		goto free;

	kthreads = kcalloc(nr_cpu_ids, sizeof(*kthreads), GFP_KERNEL);
	if (!kthreads) {
		ret = -ENOMEM;
		goto free_sbq;
	}

	for_each_online_cpu(cpu) {
		kthread = kthread_create_on_node(scale_bitmap_perf_thread, NULL,
						 cpu_to_node(cpu), "sbperf%d", cpu);
		if (IS_ERR(kthread)) {
			ret = PTR_ERR(kthread);
			goto free_kthreads;
		}
		kthread_bind(kthread, cpu);
		kthreads[cpu] = kthread;
	}

	pr_info("Starting benchmark (depth=%u, bits_per_word=%u, round_robin=%d)\n",
		sbq->map.depth, 1 << sbq->map.shift, sbq->round_robin);

	start = ktime_get();
	for_each_possible_cpu(cpu)
		wake_up_process(kthreads[cpu]);

	ret = -EBUSY;
free_kthreads:
	for_each_possible_cpu(cpu) {
		if (kthreads[cpu])
			kthread_stop(kthreads[cpu]);
	}
	end = ktime_get();
	if (ret == -EBUSY) {
		delta = ktime_to_ns(ktime_sub(end, start));
		pr_info("Benchmark took %lld.%.9lld s\n",
			delta / NSEC_PER_SEC, delta % NSEC_PER_SEC);
	}
	kfree(kthreads);
free_sbq:
	scale_bitmap_queue_free(sbq);
free:
	kfree(sbq);
	return ret;
}

module_init(scale_bitmap_perf_init);

MODULE_AUTHOR("Omar Sandoval <osandov@fb.com>");
MODULE_DESCRIPTION("scale_bitmap benchmark");
MODULE_LICENSE("GPL");
