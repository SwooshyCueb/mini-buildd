# Note: This currently needs "bash" as shell, so it's not that "POSIX"ish after all

# For documentation of function parameters, refer to the local
# variables at the very beginning of each implementation.

mbd_opt_init()
{
	local desc="${1}"
	local version="${2}"
	local name="${3}"

	MBD_OPT_SYNTAX=""
	MBD_OPT_NAME=$(if [ -z "${name}" ]; then basename "${0}"; else echo -n "${name}"; fi)
	MBD_OPT_VERSION="${version}"
	MBD_OPT_DESC="${desc}"
	MBD_OPT_POSITIONAL=0
	mbd_opt_add "h" "Show usage help."
}

mbd_opt_add()
{
	local id="${1}"
	local desc="${2}"
	local default="${3}"
	local implies="${4}"

	local idLetter="${id:0:1}"
	local syntax="-${idLetter}$(if [ "${id:1:1}" = ":" ]; then echo -n " arg"; fi)"

	MBD_OPT_SYNTAX="${MBD_OPT_SYNTAX}${id}"
	eval "MBD_OPT_DESC_${idLetter}=\"${desc}\""
	eval "MBD_OPT_DEFAULT_${idLetter}=\"${default}\""
	eval "MBD_OPT_SYNTAX_${idLetter}=\"${syntax}\""
	eval "MBD_OPT_IMPLIES_${idLetter}=\"${implies}\""
}

mbd_opt_addPos()
{
	local id="${1}"
	local desc="${2}"
	local default="${3}"

	eval "MBD_OPT_ID_POSITIONAL_${MBD_OPT_POSITIONAL}=\"${id}\""
	eval "MBD_OPT_DESC_POSITIONAL_${MBD_OPT_POSITIONAL}=\"${desc}\""
	eval "MBD_OPT_DEFAULT_POSITIONAL_${MBD_OPT_POSITIONAL}=\"${default}\""
	MBD_OPT_POSITIONAL="$((MBD_OPT_POSITIONAL+1))"
}

mbd_opt_parse()
{
	local OPTIND=1 OPTARG OPTERR=1 o
	MBD_OPT_FULLCOMMAND="$0 $@"

	# Options
	while getopts "${MBD_OPT_SYNTAX}" o; do
		if [ "${o}" = "?" ]; then
			mbd_opt_help >&2
			exit 1
		elif [ "${o}" = "h" ]; then
			mbd_opt_help
			exit 0
		fi
		eval "MBD_OPT_${o}=\"${OPTARG}\""
		local impliesVar="MBD_OPT_IMPLIES_${o}"
		for implied in ${!impliesVar}; do
			if ! mbd_opt_given ${implied}; then
				mbd_opt_set ${implied}
			fi
		done
	done

	# Positionals
	for ((i=0; i <= $((${#}-OPTIND)); ++i)) do
		local j=$((i+OPTIND))
		MBD_OPT_positional[${i}]="${!j}"
	done
}


# Show usage
mbd_opt_usage()
{
	echo -n "Usage: ${MBD_OPT_NAME}"
	for ((i=0; i < ${#MBD_OPT_SYNTAX}; ++i)); do
		local o="${MBD_OPT_SYNTAX:${i}:1}"
		if [ "${o}" != ":" ]; then
			local syntax="MBD_OPT_SYNTAX_${o}"
			echo -n " ${!syntax}"
		fi
	done
	for ((i=0; i < $((MBD_OPT_POSITIONAL)); ++i)); do
		local id="MBD_OPT_ID_POSITIONAL_${i}"
		echo -n " ${!id}"
	done
	echo
}

# Show help
mbd_opt_help()
{
	echo -e "\nHelp for ${MBD_OPT_NAME}$([ -z "${MBD_OPT_VERSION}" ] || echo -e "-${MBD_OPT_VERSION}"):\n"

	[ -z "${MBD_OPT_DESC}" ] || echo -e "${MBD_OPT_DESC}\n"

	mbd_opt_usage

	echo -e "\nOptions:"
	for ((i=0; i < ${#MBD_OPT_SYNTAX}; ++i)); do
		local o="${MBD_OPT_SYNTAX:${i}:1}"
		if [ "${o}" != ":" ]; then
			local syntax="MBD_OPT_SYNTAX_${o}"
			local desc="MBD_OPT_DESC_${o}"
			local default="MBD_OPT_DEFAULT_${o}"
			local implies="MBD_OPT_IMPLIES_${o}"
			printf " %-6s: %s\n" "${!syntax}" "${!desc}"
			if [ "${!default}" ]; then
				echo -e "         Default='${!default}'."
			fi
			if [ "${!implies}" ]; then
				echo -e "         Implies='${!implies}'."
			fi
		fi
	done
	if [ ${MBD_OPT_POSITIONAL} -gt 0 ]; then
		echo -e "Positionals:"
		for ((i=0; i < $((MBD_OPT_POSITIONAL)); ++i)); do
			local id="MBD_OPT_ID_POSITIONAL_${i}"
			local desc="MBD_OPT_DESC_POSITIONAL_${i}"
			local default="MBD_OPT_DEFAULT_POSITIONAL_${i}"
			printf " %-6s: %s\n" "${!id}" "${!desc}"
			if [ "${!default}" ]; then
				echo -e "         Default='${!default}'."
			fi
		done
	fi
}

# Check whether an option is given
mbd_opt_given()
{
	local varName="MBD_OPT_${1}"
	[ -n "${!varName+set}" ]
}

# Get option value from char identifier. Returns 1 if the option is
# not given and there is no default, 0 on success.
mbd_opt_get()
{
	local varName="MBD_OPT_${1}"
	local defaultName="MBD_OPT_DEFAULT_${1}"

	if [ "${!varName+set}" ]; then
		echo -n "${!varName}"
	elif [ "${!defaultName}" ]; then
		echo -n "${!defaultName}"
	else
		mbd_opt_error "Option ${1} not given, and has no default"
	fi
}

# Set option value from char identifier. You may use this if some
# option indirectly sets another one, for example.
mbd_opt_set()
{
	local varName="MBD_OPT_${1}"
	local varValue="${2}"

	eval "${varName}=\"${varValue}\""
}

# Check whether a positional argument is given
mbd_opt_givenPos()
{
	local index="${1}"
	[ $((index)) -lt ${#MBD_OPT_positional[*]} ]
}

# Get non-option options from index. Other behaviour like mbd_opt_get.
mbd_opt_getPos()
{
	local index="${1}"

	local defaultName="MBD_OPT_DEFAULT_POSITIONAL_${index}"
	if [ $((index)) -lt ${#MBD_OPT_positional[*]} ]; then
		echo -n "${MBD_OPT_positional[${index}]}"
	elif [ "${!defaultName}" ]; then
		echo -n "${!defaultName}"
	else
		local idName="MBD_OPT_ID_POSITIONAL_${index}"
		mbd_opt_error "Positional arg ${!idName} not given, and has no default"
	fi
}

# Little helper to (re-)assmeble option line as given
mbd_opt_assemble()
{
	for o in ${1}; do
		if mbd_opt_given ${o}; then
			echo -n "-${o} $(mbd_opt_get $o) "
		fi
	done
}

mbd_opt_error()
{
	${MBD_LOG} -s "ERROR: ${1}."
	${MBD_LOG} -s "Full command was: \"${MBD_OPT_FULLCOMMAND}\""
	mbd_opt_help | ${MBD_LOG} -s
	exit 9
}
