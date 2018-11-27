/*
 * To build this, drop this file in the top level of the btrfs-progs repository
 * and run make btrfs-clobber-dev-stats. Maybe someday libbtrfs will provide
 * this functionality.
 */

#include <stdio.h>
#include <stdlib.h>

#include "disk-io.h"
#include "transaction.h"

int main(int argc, char **argv)
{
	int status = EXIT_FAILURE;
	struct btrfs_root *root;
	struct btrfs_trans_handle *trans;
	struct btrfs_path *path;
	struct btrfs_key key;
	struct btrfs_dev_stats_item *item;
	__le64 *values;
	int ret;

	if (argc != 2) {
		fprintf(stderr, "usage: %s DEV\n", argv[0]);
		return EXIT_FAILURE;
	}

	root = open_ctree(argv[1], 0, OPEN_CTREE_WRITES);
	if (!root) {
		fprintf(stderr, "could not open filesystem\n");
		return EXIT_FAILURE;
	}

	path = btrfs_alloc_path();
	if (!path) {
		fprintf(stderr, "could not allocate path\n");
		goto out_close;
	}

	trans = btrfs_start_transaction(root, 1);
	if (IS_ERR(trans)) {
		fprintf(stderr, "could not start transaction\n");
		goto out_path;
	}

	key.objectid = BTRFS_DEV_STATS_OBJECTID;
	key.type = BTRFS_PERSISTENT_ITEM_KEY;
	key.offset = 1;
	ret = btrfs_search_slot(trans, root->fs_info->dev_root, &key, path, 0,
				1);
	if (ret < 0) {
		fprintf(stderr, "error while searching for dev stats item\n");
		goto out_path;
	}
	if (ret > 0) {
		fprintf(stderr, "could not find dev stats item\n");
		goto out_path;
	}

	item = btrfs_item_ptr(path->nodes[0], path->slots[0],
			      struct btrfs_dev_stats_item);
	values = btrfs_dev_stats_values(path->nodes[0], item);
	values[BTRFS_DEV_STAT_WRITE_ERRS] = cpu_to_le64(1);
	btrfs_mark_buffer_dirty(path->nodes[0]);
	btrfs_commit_transaction(trans, root);

	status = EXIT_SUCCESS;
out_path:
	btrfs_free_path(path);
out_close:
	close_ctree(root);
	return status;
}
