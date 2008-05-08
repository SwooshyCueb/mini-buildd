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
MBD_LIB="/usr/lib/mini-buildd"

MBD_REPCONFIGFILE="${MBD_HOME}/.mini-buildd.conf"
MBD_REPCONFIGVARS="mbd_rephost mbd_httpport mbd_sshport mbd_mail mbd_id mbd_dists mbd_archs mbd_archall"
MBD_BLDCONFIGFILE="${MBD_HOME}/.mini-buildd-bld.conf"
MBD_BLDCONFIGVARS="mbd_rephttphost mbd_lvm_vg"

MBD_SBUILDCONFIGFILE="${MBD_HOME}/.sbuildrc"
MBD_DPUTCONFIGFILE="${MBD_HOME}/.dput.cf"

MBD_SSHSECKEYFILE="${MBD_HOME}/.ssh/id_dsa"
MBD_SSHPUBKEYFILE="${MBD_HOME}/.ssh/id_dsa.pub"

MBD_GNUPGSECRING="${MBD_HOME}/.gnupg/secring.gpg"

MBD_MDINSTALLCONFIGFILE="${MBD_HOME}/.mini-dinstall.conf"

MBD_HTML_INDEXFILE="${MBD_HOME}/public_html/index.html"

# Packages that must be installed in (source) build chroots
MBD_CHROOT_EXTRA_PACKAGES="fakeroot lintian"
MBD_SCHROOTCONFIGFILE="/etc/schroot/schroot.conf"

# Maintainer name of autobuilder (goes to .sbuildrc, and used to reject direct binary uploads).
MBD_AUTOBUILD_MAINTAINER="Mini-Buildd Builder"

MBD_LOG="logger -t mini-buildd[`basename $0`] -p daemon.info"

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
	if [ "`id -u -n`" != "${user}" ]; then
		mbd_opt_error "Must run as user ${user}, not `id -u -n`"
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
	local key=`mbdCatUrl "http://${host}:${mbd_httpport}/~mini-buildd/ssh_key.asc"`
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

mbdBldGetMirror()
{
	local dist="${1}"
	local mirror=""
	for raw_mirror in ${mbd_debian_mirror}; do
		local d=`echo "${raw_mirror}" | cut -d: -f1`
		if [ "${d}" = "all" -o "${d}" = "${dist}" ]; then
			mirror=`echo -n "${raw_mirror}" | cut -d: -f2-`
		fi
	done
	echo -n "${mirror}"
}

# Parse changes file
mbdParseCF()
{
	local cf="${1}"
	local GREP1="grep --max-count=1"
	mbdParseCF_dist=`${GREP1} "^Distribution" "${cf}" | cut -d" " -f2-`
	mbdParseCF_arch=`echo "${cf}" | rev | cut -d. -f2 | cut -d_ -f1 | rev`
	mbdParseCF_package=`echo "${cf}" | rev | cut -d_ -f2- | cut -d/ -f1 | rev`
	mbdParseCF_files="`basename "${cf}"` `${GREP1} "^Files:" -A100 ${cf} | grep "^ .\+" | rev | cut -d" " -f1 | rev`"
	mbdParseCF_source="`${GREP1} "^Source: " ${cf} | cut -d' ' -f2-`"
	mbdParseCF_version="`${GREP1} "^Version: " ${cf} | cut -d' ' -f2-`"
	mbdParseCF_maintainer="`${GREP1} "^Maintainer: " ${cf} | cut -d' ' -f2-`"
	mbdParseCF_changed_by="`${GREP1} "^Changed-By: " ${cf} | cut -d' ' -f2-`"
	# For convenience
	mbdParseCF_upstream_version="`echo "${mbdParseCF_version}" | cut -d- -f1`"
	mbdParseCF_orig_tarball="${mbdParseCF_source}_${mbdParseCF_upstream_version}.orig.tar.gz"
}

# Parse build host
mbdParseBH()
{
	local bldhost="${1}"
	mbdParseBH_arch=`echo "${bldhost}" | cut -d':' -f1`
	mbdParseBH_host=`echo "${bldhost}" | cut -d':' -f2`
	if [ "${mbdParseBH_arch}" = "${mbd_archall}" ]; then
		mbdParseBH_options="-A"
	else
		mbdParseBH_options=""
	fi
}

mbdGetBH()
{
	local arch="${1}"
	for b in ${mbd_bldhosts}; do
		mbdParseBH "${b}"
		if [ "${mbdParseBH_arch}" = "${arch}" -o "${arch}" = "all" -a "${mbdParseBH_arch}" = "${mbd_archall}" ]; then
			echo -n "${mbdParseBH_host}"
			return 0
		fi
	done
	return 1
}

# Build ID to bld dir converter
mbdBId2BDir()
{
	echo -n "${1}" | tr "/" "_"
}

# Delete marked config snippet from a file
mbdDeleteMarkedConfig()
{
	local conffile="${1}"

	local marks=`grep -n -m 2 "${MBD_CONFIG_MARK}" "${conffile}" | cut -d: -f1`
	local m0=`echo ${marks} | cut -d" " -f1`
	local m1=`echo ${marks} | cut -d" " -f2`

	if [ -n "${m0}" -a -n "${m1}" ]; then
		sed "${m0},${m1}d" "${conffile}" >"${conffile}.tmp"
		mv "${conffile}.tmp" "${conffile}"
		${MBD_LOG} -s "Deleted marked config from ${conffile}."
	fi
}

# Get versions of known basis distributions
mbdBasedist2Version()
{
	case ${1} in
		woody)
			echo -n "30"
			;;
		sarge)
			echo -n "31"
			;;
		etch)
			echo -n "40"
			;;
		*)
			return 1
			;;
	esac
}

mbdGetMandatoryVersionPart()
{
	local dist=`echo "${1}" | cut -d'-' -f1`
	local version=`mbdBasedist2Version ${dist}`
	if [ -n "${version}" ]; then
		echo -n "~${mbd_id}${version}+"
	fi
}

mbdCheckVersion()
{
	local dist="${1}"
	local version="${2}"
	local mandatory=`mbdGetMandatoryVersionPart "${dist}"`
	if ! echo "${version}" | grep --quiet "${mandatory}"; then
		${MBD_LOG} -s "Mandatory version part \"${mandatory}\" missing from \"${version}\"."
		return 1
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
