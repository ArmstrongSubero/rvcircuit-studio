% gdb -help         	print startup help, show switches
*% gdb object      	normal debug 
*% gdb object core 	core debug (must specify core file)
%% gdb object pid  	attach to running process
% gdb        		use file command to load object 
*(gdb) help        	list command classes
(gdb) help running      list commands in one command class
(gdb) help run        	bottom-level help for a command "run" 
(gdb) help info         list info commands (running program state)
(gdb) help info line    help for a particular info command
(gdb) help show         list show commands (gdb state)
(gdb) help show commands        specific help for a show comma
*(gdb) break main       set a breakpoint on a function
*(gdb) break 101        set a breakpoint on a line number
*(gdb) break basic.c:101        set breakpoint at file and line (or function)
*(gdb) info breakpoints        show breakpoints
*(gdb) delete 1         delete a breakpoint by number
(gdb) delete        	delete all breakpoints (prompted)
(gdb) clear             delete breakpoints at current line
(gdb) clear function    delete breakpoints at function
(gdb) clear line        delete breakpoints at line
(gdb) disable 2         turn a breakpoint off, but don't remove it
(gdb) enable 2          turn disabled breakpoint back on
(gdb) tbreak function|line        set a temporary breakpoint
(gdb) commands break-no ... end   set gdb commands with breakpoint
(gdb) ignore break-no count       ignore bpt N-1 times before activation
(gdb) condition break-no expression         break only if condition is true
(gdb) condition 2 i == 20         example: break on breakpoint 2 if i equals 20
(gdb) watch expression        set software watchpoint on variable
(gdb) info watchpoints        show current watchpoints
*(gdb) run        	run the program with current arguments
*(gdb) run args redirection        run with args and redirection
(gdb) set args args...        set arguments for run 
(gdb) show args        show current arguments to run
*(gdb) cont            continue the program
*(gdb) step            single step the program; step into functions
(gdb) step count       singlestep \fIcount\fR times
*(gdb) next            step but step over functions 
(gdb) next count       next \fIcount\fR times
*(gdb) CTRL-C          actually SIGINT, stop execution of current program 
*(gdb) attach process-id        attach to running program
*(gdb) detach        detach from running program
*(gdb) finish        finish current function's execution
(gdb) kill           kill current executing program
*(gdb) bt        	print stack backtrace
(gdb) frame        	show current execution position
(gdb) up        	move up stack trace  (towards main)
(gdb) down        	move down stack trace (away from main)
*(gdb) info locals      print automatic variables in frame
(gdb) info args         print function parameters 
(gdb) info registers        	print registers sans floats
(gdb) info all-registers        print all registers
(gdb) print/x $pc        	print one register
(gdb) stepi        		single step at machine level
(gdb) si        		single step at machine level
(gdb) nexti        		single step (over functions) at machine level
(gdb) ni        		single step (over functions) at machine level
(gdb) display/i $pc        	print current instruction in display
(gdb) x/x &gx        		print variable gx in hex
(gdb) info line 22        	print addresses for object code for line 22
(gdb) info line *0x2c4e         print line number of object code at address
(gdb) x/10i main        	disassemble first 10 instructions in \fImain\fR
(gdb) disassemble addr          dissassemble code for function around addr
(gdb) info registers        	print registers sans floats
(gdb) info all-registers        print all registers
(gdb) print/x $pc        	print one register
(gdb) stepi        		single step at machine level
(gdb) si        		single step at machine level
(gdb) nexti        		single step (over functions) at machine level
(gdb) ni        		single step (over functions) at machine level
(gdb) display/i $pc        	print current instruction in display
(gdb) x/x &gx        		print variable gx in hex
(gdb) info line 22        	print addresses for object code for line 22
(gdb) info line *0x2c4e         print line number of object code at address
(gdb) x/10i main        	disassemble first 10 instructions in \fImain\fR
(gdb) disassemble addr          dissassemble code for function around addr
(gdb) show commands        	print command history (>= gdb 4.0)
(gdb) info editing       	print command history (gdb 3.5)
(gdb) ESC-CTRL-J        	switch to vi edit mode from emacs edit mode
(gdb) set history expansion on       turn on c-shell like history
(gdb) break class::member       set breakpoint on class member. may get menu
(gdb) list class::member        list member in class
(gdb) ptype class               print class members
(gdb) print *this        	print contents of this pointer
(gdb) rbreak regexpr     	useful for breakpoint on overloaded member name