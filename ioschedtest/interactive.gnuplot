set style data boxplot
set style fill solid 0.5 border -1

set title "Completion Latency of Interactive Reader with Heavy Writer"
set ylabel "Latency (ms)"
set yrange [0:]

unset key
set xtics ("Noop" 1, "Deadline" 2, "CFQ" 3, "blk-mq" 4, "BFQ" 5)
plot "interactive/noop_clat.log" using (1):($2 / 1000.0), \
     "interactive/deadline_clat.log" using (2):($2 / 1000.0), \
     "interactive/cfq_clat.log" using (3):($2 / 1000.0), \
     "interactive/blk-mq_clat.log" using (4):($2 / 1000.0), \
     "interactive/bfq_clat.log" using (5):($2 / 1000.0)
