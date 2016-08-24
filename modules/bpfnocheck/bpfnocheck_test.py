#!/usr/bin/env python3

import bcc

bpf_text = r"""
#include <linux/blkdev.h>

int kprobe__blk_flush_plug_list(struct pt_regs *ctx, struct blk_plug *plug, bool from_schedule)
{
	struct request *rq;

	bpf_trace_printk("blk_flush_plug_list\n");
	bpf_trace_printk("  list=\n");
	list_for_each_entry(rq, &plug->list, queuelist)
		bpf_trace_printk("    0x%p\n", rq);

	bpf_trace_printk("  mq_list=\n");
	list_for_each_entry(rq, &plug->mq_list, queuelist)
		bpf_trace_printk("    0x%p\n", rq);

	return 0;
}
"""

def main():
    b = bcc.BPF(text=bpf_text)
    while True:
        b.kprobe_poll()

if __name__ == '__main__':
    main()
