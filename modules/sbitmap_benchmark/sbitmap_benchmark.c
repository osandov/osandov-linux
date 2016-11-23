#include <linux/kthread.h>
#include <linux/module.h>
#include <linux/sbitmap.h>

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

enum sbitmap_benchmark_type {
	BENCHMARK_SYNC_GET_CLEAR = 0,
	BENCHMARK_FULL_GET_CLEAR = 1,
};
static int benchmark = BENCHMARK_SYNC_GET_CLEAR;
module_param(benchmark, int, S_IRUGO);
MODULE_PARM_DESC(benchmark, "Benchmark to run (0=sync get/clear, 1=full get/clear)");

static unsigned int iterations = 1000000;
module_param(iterations, uint, S_IRUGO);
MODULE_PARM_DESC(iterations, "Number of benchmark iterations");

static struct task_struct **kthreads;
static struct sbitmap_queue *sbq;

/*
 * Repeatedly get and clear a bit.
 */
static void sbitmap_benchmark_sync_get_clear(unsigned int cpu)
{
	unsigned int i;
	int nr;

	for (i = 0; i < iterations; i++) {
		nr = __sbitmap_queue_get(sbq);
		if (nr >= 0)
			sbitmap_queue_clear(sbq, nr, cpu);
	}
}

/*
 * Repeatedly fill and empty the bitmap with get and clear.
 */
static void sbitmap_benchmark_full_get_clear(unsigned int cpu, int *bitnrs)
{
	unsigned int i;
	int n = 0;
	int nr;

	for (i = 0; i < iterations; i++) {
		nr = __sbitmap_queue_get(sbq);
		if (nr >= 0) {
			bitnrs[n++] = nr;
		} else {
			while (n)
				sbitmap_queue_clear(sbq, bitnrs[--n], cpu);
		}
	}
	while (n)
		sbitmap_queue_clear(sbq, bitnrs[--n], cpu);
}

static int sbitmap_benchmark_thread(void *data)
{
	ktime_t start, end;
	int *bitnrs;
	s64 delta;
	int cpu;

	bitnrs = kmalloc_array(depth, sizeof(*bitnrs), GFP_KERNEL);
	if (!bitnrs) {
		pr_err("Out of memory\n");
		return -ENOMEM;
	}

	cpu = get_cpu();
	start = ktime_get();
	switch (benchmark) {
	case BENCHMARK_SYNC_GET_CLEAR:
		sbitmap_benchmark_sync_get_clear(cpu);
		break;
	case BENCHMARK_FULL_GET_CLEAR:
		sbitmap_benchmark_full_get_clear(cpu, bitnrs);
		break;
	}
	end = ktime_get();
	delta = ktime_to_ns(ktime_sub(end, start));
	put_cpu();

	pr_info("CPU %d took %lld.%.9lld s\n", cpu,
		delta / NSEC_PER_SEC, delta % NSEC_PER_SEC);

	kfree(bitnrs);

	while (!kthread_should_stop()) {
		__set_current_state(TASK_INTERRUPTIBLE);
		schedule();
	}

	return 0;
}

static int __init sbitmap_perf_init(void)
{
	ktime_t start, end;
	s64 delta;
	struct task_struct *kthread;
	int cpu;
	int ret;

	sbq = kzalloc_node(sizeof(*sbq), GFP_KERNEL, home_node);
	if (!sbq)
		return -ENOMEM;

	ret = sbitmap_queue_init_node(sbq, depth, shift, round_robin,
				      GFP_KERNEL, home_node);
	if (ret)
		goto free;

	kthreads = kcalloc(nr_cpu_ids, sizeof(*kthreads), GFP_KERNEL);
	if (!kthreads) {
		ret = -ENOMEM;
		goto free_sbq;
	}

	for_each_online_cpu(cpu) {
		kthread = kthread_create_on_node(sbitmap_benchmark_thread, NULL,
						 cpu_to_node(cpu), "sbperf%d", cpu);
		if (IS_ERR(kthread)) {
			ret = PTR_ERR(kthread);
			goto free_kthreads;
		}
		kthread_bind(kthread, cpu);
		kthreads[cpu] = kthread;
	}

	pr_info("Starting benchmark (depth=%u, bits_per_word=%u, round_robin=%d)\n",
		sbq->sb.depth, 1 << sbq->sb.shift, sbq->round_robin);

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
	sbitmap_queue_free(sbq);
free:
	kfree(sbq);
	return ret;
}

module_init(sbitmap_perf_init);

MODULE_AUTHOR("Omar Sandoval <osandov@fb.com>");
MODULE_DESCRIPTION("sbitmap benchmark");
MODULE_LICENSE("GPL");
