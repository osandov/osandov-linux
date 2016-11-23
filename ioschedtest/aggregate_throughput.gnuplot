set style data histogram
set style histogram cluster gap 1
set style fill solid 0.5 border -1

set auto x
set ylabel "Throughput (MB/s)"
set yrange [0:]

plot for [COL=2:6] 'aggregate/throughput.dat' using COL:xtic(1) title col
