set style data linespoints

set title "Throughput of Sequential Reader with Write Bursts"
set xlabel "Time (s)"
set ylabel "Throughput (MB/s)"
set xrange [0:]
set yrange [0:]

plot "writeburst/noop_bw.log" using ($1 / 1000.0):($2 / 1000.0) title "Noop", \
     "writeburst/deadline_bw.log" using ($1 / 1000.0):($2 / 1000.0) title "Deadline", \
     "writeburst/cfq_bw.log" using ($1 / 1000.0):($2 / 1000.0) title "CFQ", \
     "writeburst/blk-mq_bw.log" using ($1 / 1000.0):($2 / 1000.0) title "blk-mq", \
     "writeburst/bfq_bw.log" using ($1 / 1000.0):($2 / 1000.0) title "BFQ"
