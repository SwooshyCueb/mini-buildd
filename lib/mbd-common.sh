# Notation conventions:
#  (Debconf) configuration variables: "mbd_foo"
#  Constants                        : "MBD_FOO"
#  Temporary global variables       : "MBD_TMP_FOO"
#  Functions                        : "mbdFoo"
#  Parse results from "mbdParseFoo" : "mbdParseFoo_bar"
#  Option parser (mbd-libopt.sh)    : Uses mbd_opt_ as function prefix, MBD_OPT_ as prefix for global vars.
#
# In comments:
#  @todo: Missing code.
#  @hack: Works, but should be fixed eventually.
#  @bug : Known bug.

MBD_HOME="/home/mini-buildd"

# Use dirname if that's correct (mbd-* scripts); else use system path (postinst et.al.).
MBD_LIB=$(dirname ${0})
if ! [ -e "${MBD_LIB}/mbd-common.sh" ]; then
	MBD_LIB="/usr/share/mini-buildd"
fi

MBD_REPCONFIGFILE="${MBD_HOME}/.mini-buildd.conf"
MBD_REPCONFIGVARS="mbd_id mbd_rephost mbd_httpport mbd_sshport mbd_mail mbd_extdocurl mbd_dists mbd_archs mbd_archall"
MBD_BLDCONFIGFILE="${MBD_HOME}/.mini-buildd-bld.conf"
MBD_BLDCONFIGVARS="mbd_defer mbd_rephttphost mbd_bldhost mbd_lvm_vg"

MBD_LOCALCONFIG="${MBD_HOME}/.mini-buildd"

MBD_SBUILDCONFIGFILE="${MBD_HOME}/.sbuildrc"
MBD_DPUTCONFIGFILE="${MBD_HOME}/.dput.cf"

MBD_SSHSECKEYFILE="${MBD_HOME}/.ssh/id_dsa"
MBD_SSHPUBKEYFILE="${MBD_HOME}/.ssh/id_dsa.pub"

MBD_GNUPGSECRING="${MBD_HOME}/.gnupg/secring.gpg"
MBD_GNUPG_KEYNAME="Mini-Buildd Automatic Signing Key"

MBD_MDINSTALLCONFIGFILE="${MBD_HOME}/.mini-dinstall.conf"

MBD_HTML_INDEXFILE="${MBD_HOME}/public_html/index.html"

MBD_SCHROOTCONFIGFILE="/etc/schroot/schroot.conf"

# Maintainer name of autobuilder (goes to .sbuildrc, and used to reject direct binary uploads).
MBD_AUTOBUILD_MAINTAINER="Mini-Buildd Builder"

MBD_INCOMING="${MBD_HOME}/rep/mini-dinstall/incoming"
MBD_INCOMING_BPO="${MBD_INCOMING}/backports"

MBD_LOG="logger -t mini-buildd[$(basename -- "${0}")] -p user.info"

# For schroot: Marks auto-generated configuration snippets
MBD_CONFIG_MARK="# MINI-BUILDD AUTOGENERATION MARK"

# Always source getopt library
. ${MBD_LIB}/mbd-libopt.sh

# Status from retval support
MBD_PREINSTALL_STATUSES[0]="BUILT"
MBD_PREINSTALL_STATUSES[1]="FTBFS"
MBD_PREINSTALL_STATUSES[2]="REJECT"

MBD_QACHECK_STATUSES[0]="FINE"
MBD_QACHECK_STATUSES[1]="WARN"
MBD_QACHECK_STATUSES[2]="FAIL"

mbdRetval2Status()
{
	local id="${1}"
	local retval="${2}"
	local var="MBD_${id}_STATUSES[${retval}]"
	local result="${!var}"
	if [ -z "${result}" ]; then
		result="INTERNAL_ERROR"
	fi
	echo -n "${result}"
}

mbdCheckUser()
{
	local user="${1}"
	if [ "$(id -u -n)" != "${user}" ]; then
		mbd_opt_error "Must run as user ${user}, not $(id -u -n)"
	fi
}

mbdCheckFile()
{
	local file="${1}"
	if [ ! -f "${file}" ]; then
		mbd_opt_error "No such file: ${file}"
	fi
}

mbdCatUrl()
{
	local url="${1}"
	wget --quiet --output-document=- "${url}"
	return $?
}

mbdGetUrl()
{
	local file="${1}"
	local url="${2}"
	if mbdCatUrl "${url}" >"${file}.tmp"; then
		mv "${file}.tmp" "${file}"
		${MBD_LOG} -s "${file} downloaded (from ${url})."
		return 0
	else
		rm -f "${file}.tmp"
		${MBD_LOG} -s "Error retrieving ${url}."
		if [ ! -e "${file}" ]; then
			echo "# Error downloading ${file} from ${url}; please reconfigure package or rerun $0." >"${file}"
		fi
		return 1
	fi
}

mbdUpdateSshKeyring()
{
	local host="${1}"
	local key=$(mbdCatUrl "http://${host}:${mbd_httpport}/~mini-buildd/ssh_key.asc")
	if [ -n "${key}" ]; then
		if ! grep -q "${key}" .ssh/authorized_keys; then
			echo "${key}" >>.ssh/authorized_keys
			${MBD_LOG} -s "SSH keyring: ${host} added."
		else
			${MBD_LOG} -s "SSH keyring: ${host} up to date."
		fi
	else
		${MBD_LOG} -s "ERROR: Retrieving ssh key for ${host}."
	fi
}

mbdParseCFTopChanges()
{
	local source="${1}"
	local cf="${2}"

	local regexHeader="^ ${source} (.\+) .\+; urgency=.\+\$"

	grep --max-count=1 -A100 "^Changes:" "${cf}" |
	(
		# Skip ^Changes line and topmost header
		read
		read
		while read; do
			if echo "${REPLY}" | grep --quiet "${regexHeader}"; then
				# Another header? Leave; we only want the topmost version
				break
			fi
			echo "${REPLY}"
		done
	)
}


# Parse auto-backports list from changes file (OUCH!).
mbdParseCFAutoBackports()
{
	local source="${1}"
	local cf="${2}"

	local regex="*[[:space:]]*MINI_BUILDD:[[:space:]]*AUTO_BACKPORTS:"

	mbdParseCFTopChanges "${source}" "${cf}" |
	(
		local reading=false
		while read; do
			if echo "${REPLY}" | grep --quiet "${regex}"; then
				# Line with identifier
				echo -n "${REPLY}" | cut -d: -f3-
				reading=true
			elif ${reading} && ( [ -z "${REPLY}" ] || echo "${REPLY}" | grep --quiet -e "^ \." -e "\[" -e "*" -e "^[^[:space:]]\+" ); then
				# No further entries (changelog), new entry (both), end of entries (changes): break
				break;
			elif ${reading}; then
				# The whole line belongs to us
				echo -n "${REPLY}"
			fi
		done
	)
}

# Parse changes file
mbdParseCF()
{
	local cf="${1}"
	local GREP1="grep --max-count=1"
	mbdParseCF_dist=$(${GREP1} "^Distribution" "${cf}" | cut -d" " -f2-)
	mbdParseCF_arch=$(echo "${cf}" | rev | cut -d. -f2 | cut -d_ -f1 | rev)
	mbdParseCF_package=$(echo "${cf}" | rev | cut -d_ -f2- | cut -d/ -f1 | rev)
	mbdParseCF_files="$(basename "${cf}") $(${GREP1} "^Files:" -A100 ${cf} | grep "^ .\+" | rev | cut -d" " -f1 | rev)"
	mbdParseCF_source=$(${GREP1} "^Source: " ${cf} | cut -d' ' -f2-)
	mbdParseCF_version=$(${GREP1} "^Version: " ${cf} | cut -d' ' -f2-)
	mbdParseCF_maintainer=$(${GREP1} "^Maintainer: " ${cf} | cut -d' ' -f2-)
	mbdParseCF_changed_by=$(${GREP1} "^Changed-By: " ${cf} | cut -d' ' -f2-)

	# For convenience
	mbdParseCF_upstream_version=$(echo "${mbdParseCF_version}" | cut -d- -f1)
	mbdParseCF_orig_tarball="${mbdParseCF_source}_${mbdParseCF_upstream_version}.orig.tar.gz"

	# Mini-buildd controls via changelog entries
	mbdParseCF_mbd_backport_mode=false
	if mbdParseCFTopChanges "${mbdParseCF_source}" "${cf}" | grep --quiet "MINI_BUILDD: BACKPORT_MODE"; then
		mbdParseCF_mbd_backport_mode=true
	fi
	mbdParseCF_mbd_auto_backports=$(mbdParseCFAutoBackports "${mbdParseCF_source}" "${cf}" | tr -d '[:space:]' | tr ',' ' ')
}

# Parse build host for arch
mbdParseArch() # arch
{
	local arch="${1}"
	local bldhost="mbd_bldhost_${arch}"
	local debopts="mbd_deb_build_options_${arch}"

	mbdParseArch_arch="${arch}"
	mbdParseArch_host="${!bldhost}"
	mbdParseArch_debopts="${!debopts}"
	if [ "${arch}" = "${mbd_archall}" ]; then
		mbdParseArch_sbuildopts="--arch-all"
	else
		mbdParseArch_sbuildopts=""
	fi
}

# Transform a debconf ("a, b") to a shell ("a b") list.
mbdD2SList()
{
	echo -n "${1}" | tr -d ","
}

mbdInList()
{
	local token="${1}"
	local list="${2}"
	local t
	for t in ${list}; do
		if [ "${t}" = "${token}" ]; then
			return 0
		fi
	done
	return 1
}

# Generate a shell list of hostnames, omit duplicates (multiarch hosts).
mbdGetBldHosts()
{
	local result=""
	local arch=""
	for arch in $(mbdD2SList "${mbd_archs}"); do
		local bldhost="mbd_bldhost_${arch}"
		if ! mbdInList "${!bldhost}" "${result}"; then
			result="${result} ${!bldhost}"
		fi
	done
	echo -n "${result}"
}

# Get list of archs this build host is responsible for
mbdGetArchs()
{
	local bldhost="${1}"
	for arch in $(mbdD2SList "${mbd_archs}"); do
		local b="mbd_bldhost_${arch}"
		if [ "${bldhost}" = "${!b}" ]; then
			echo -n "${arch} "
		fi
	done
}

# Build id to bld dir converter; build dir must be unique for multi-arch host, so we also add -${arch} here.
# Build id  is "PACKAGE/VERSION/TIMESTAMP"
# Build dir is "PACKAGE_VERSION_TIMESTAMP-ARCH"
mbdBId2BDir() # arch buildid
{
	if [ -z "${1}" ]; then
		${MBD_LOG} -s "INTERNAL ERROR: mbdBId2BDir called w/o arch."
		exit 3
	fi
	echo -n "${2}-${1}" | tr "/" "_"
}

# Delete marked config snippet from a file
mbdDeleteMarkedConfig()
{
	local conffile="${1}"

	local marks=$(grep -n -m 2 "${MBD_CONFIG_MARK}" "${conffile}" | cut -d: -f1)
	local m0=$(echo ${marks} | cut -d" " -f1)
	local m1=$(echo ${marks} | cut -d" " -f2)

	if [ -n "${m0}" -a -n "${m1}" ]; then
		sed "${m0},${m1}d" "${conffile}" >"${conffile}.tmp"
		mv "${conffile}.tmp" "${conffile}"
		${MBD_LOG} -s "Deleted marked config from ${conffile}."
	fi
}

# etch-ID              -> "etch-ID etch-ID-experimental"
# etch-ID-experimental -> "etch-ID etch-ID-experimental"
mbdExpandDists()
{
	for dist in ${1}; do
		local d="$(echo "${dist}" | sed "s/-experimental\$//")"
		echo -n "${d} ${d}-experimental "
	done
}

# Get versions of known basis distributions
mbdBasedist2Version()
{
	# Known base distributions
	local woody=30
	local sarge=31
	local etch=40
	local lenny=50
	local sid=SID

	local version=${!1}
	if [ -z "${version}" ]; then
		${MBD_LOG} -s "ERROR: Unknown base dist ${1}."
		return 1
	fi
	echo -n "${version}"
}

mbdGetMandatoryVersionPart()
{
	local dist=$(echo "${1}" | cut -d'-' -f1)
	local version=$(mbdBasedist2Version ${dist})
	if [ -n "${version}" ]; then
		echo -n "~${mbd_id}${version}+"
		if echo -n "${1}" | grep -q ".*-experimental\$"; then
			echo -n "0"
		else
			echo -n "[1-9]"
		fi
	fi
}

mbdLvmVgName()
{
	if [ "${mbd_lvm_vg}" = "auto" ]; then
		echo -n "mini-buildd"
	else
		echo -n "${mbd_lvm_vg}"
	fi
}

# Prefer arch over any, if defined
mbdGetSrcVar() # dist kind arch
{
	local srcAny="mbd_src_${1}_${2}_any"
	local srcArch="mbd_src_${1}_${2}_${arch}"
	local src="${srcAny}"
	if [ -n "${!srcArch}" ]; then
		echo -n "${srcArch}"
	else
		echo -n "${srcAny}"
	fi
}

# Generates sources.list or preferences to stdout; Info log to
# stderr.  Respect env AUTH_VERBOSITY if we are run from schroot
# setup.
mbdGenConf()
{
	# File type: sources or preferences
	local ftype="${1}"
	# Base distribution
	local dist="${2}"
	# Kinds: base, mbd, extra
	local kinds="${3}"
	# Arch: Also search for specialised arch sources list
	local arch="${4}"
	# noheader: Omit infor headers.
	local noheader="${5}"

	# Generate local source list variable for ourselves (mbd)
	eval "local mbd_src_${dist}_mbd_any=\"http://${mbd_rephost}/~mini-buildd/rep ${dist}-${mbd_id}/\""
	eval "local mbd_src_${dist}_mbd_experimental_any=\"http://${mbd_rephost}/~mini-buildd/rep ${dist}-${mbd_id}-experimental/\""

	for kind in ${kinds}; do
		local src=$(mbdGetSrcVar ${dist} ${kind} ${arch})
		if [ -n "${!src}" ]; then
			[ "${noheader}" == "noheader" ] || echo "# ${dist}: ${kind}"
			# Multiple lines my be given separated via \n
			echo -e "${!src}" |
			(
				while read; do
					if [ -n "${REPLY}" ]; then
						OUTPUT=""
						case ${ftype} in
							"sources")
								OUTPUT=$(echo "${REPLY}" | cut -d';' -f1)
								;;
							"preferences")
								PIN_REGEX='^.+\;.+\;[+-0123456789]+$'
								if [[ "${REPLY}" =~ ${PIN_REGEX} ]]; then
									APT_PIN=$(echo "${REPLY}" | cut -d';' -f2)
									APT_PRIO=$(echo "${REPLY}" | cut -d';' -f3)
									OUTPUT="Package: *\nPin: ${APT_PIN}\nPin-Priority: ${APT_PRIO}\n"
								fi
								;;
							*)
								${MBD_LOG} -s "ERROR: Wrong internal call of mbdGenFile ${@}"
								return 1
								;;
						esac
						if [ -n "${OUTPUT}" ]; then
							echo -e "${OUTPUT}"
							[ "${AUTH_VERBOSITY}" == "quiet" ] || ${MBD_LOG} -s "${ftype} added: ${OUTPUT}"
						fi
					fi
				done
			)
		fi
	done
}

mbdGenSources()
{
	mbdGenConf sources $@
}

mbdGenPreferences()
{
	mbdGenConf preferences $@
}
