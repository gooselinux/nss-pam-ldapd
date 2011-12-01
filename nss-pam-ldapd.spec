Name:		nss-pam-ldapd
Version:	0.7.5
Release:	3%{?dist}
Summary:	An nsswitch module which uses directory servers
Group:		System Environment/Base
License:	LGPLv2+
URL:		http://arthurdejong.org/nss-pam-ldapd/
Source0:	http://arthurdejong.org/nss-pam-ldapd/nss-pam-ldapd-%{version}.tar.gz
Source1:	http://arthurdejong.org/nss-pam-ldapd/nss-pam-ldapd-%{version}.tar.gz.sig
Source2:	nslcd.init
Patch0:		nss-pam-ldapd-default.patch
BuildRoot:	%{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:	openldap-devel, krb5-devel
Obsoletes:	nss-ldapd < 0.7
Provides:	nss-ldapd = %{version}-%{release}

# Pull in the pam_ldap module, which is currently bundled with nss_ldap, to
# keep upgrades from removing the module.  We currently disable nss-pam-ldapd's
# own pam_ldap.so until it's more mature.
Requires:	/%{_lib}/security/pam_ldap.so
# Pull in nscd, which is recommended.
Requires:	nscd
Requires(post):		/sbin/ldconfig, chkconfig, grep, sed
Requires(preun):	chkconfig, initscripts
Requires(postun):	/sbin/ldconfig, initscripts

%description
The nss-pam-ldapd daemon, nslcd, uses a directory server to look up name
service information (users, groups, etc.) on behalf of a lightweight
nsswitch module.

%prep
%setup -q
%patch0 -p0 -b .default

%build
%configure --libdir=/%{_lib} --disable-pam
make %{?_smp_mflags}

%install
rm -rf $RPM_BUILD_ROOT
make install DESTDIR=$RPM_BUILD_ROOT
mkdir -p $RPM_BUILD_ROOT/{%{_initddir},%{_libdir}}
install -p -m755 %{SOURCE2} $RPM_BUILD_ROOT/%{_initddir}/nslcd
# Follow glibc's convention and provide a .so symlink so that people who know
# what to expect can link directly with the module.
if test %{_libdir} != /%{_lib} ; then
	touch $RPM_BUILD_ROOT/rootfile
	relroot=..
	while ! test -r $RPM_BUILD_ROOT/%{_libdir}/$relroot/rootfile ; do
		relroot=../$relroot
	done
	ln -s $relroot/%{_lib}/libnss_ldap.so.2 \
		$RPM_BUILD_ROOT/%{_libdir}/libnss_ldap.so
	rm $RPM_BUILD_ROOT/rootfile
fi
cat >> $RPM_BUILD_ROOT/%{_sysconfdir}/nslcd.conf << EOF
uid nslcd
gid ldap
EOF
touch -r nslcd.conf $RPM_BUILD_ROOT/%{_sysconfdir}/nslcd.conf
mkdir -p 0755 $RPM_BUILD_ROOT/var/run/nslcd

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)
%doc AUTHORS ChangeLog COPYING HACKING NEWS README TODO
%{_sbindir}/*
/%{_lib}/*.so.*
%{_mandir}/*/*
%attr(0600,root,root) %config(noreplace) /etc/nslcd.conf
%attr(0755,root,root) %{_initddir}/nslcd
%attr(0755,nslcd,root) /var/run/nslcd
# This would be the only thing in the -devel subpackage, so we include it.
/%{_libdir}/*.so

%pre
getent group  ldap  > /dev/null || \
/usr/sbin/groupadd -r -g 55 ldap
getent passwd nslcd > /dev/null || \
/usr/sbin/useradd -r -g ldap -c 'LDAP Client User' \
    -u 65 -d / -s /sbin/nologin nslcd 2> /dev/null || :

%post
# The usual stuff.
/sbin/chkconfig --add nslcd
/sbin/ldconfig
# Import important non-default settings from nss_ldap or pam_ldap configuration
# files, but only the first time this package is installed.
comment="This comment prevents repeated auto-migration of settings."
if test -s /etc/nss-ldapd.conf ; then
	source=/etc/nss-ldapd.conf
elif test -s /etc/nss_ldap.conf ; then
	source=/etc/nss_ldap.conf
elif test -s /etc/pam_ldap.conf ; then
	source=/etc/pam_ldap.conf
else
	source=/etc/ldap.conf
fi
target=/etc/nslcd.conf
if ! grep -q -F "# $comment" $target 2> /dev/null ; then
	# Try to make sure we only do this the first time.
	echo "# $comment" >> $target
	if egrep -q '^uri[[:blank:]]' $source 2> /dev/null ; then
		# Comment out the packaged default host/uri and replace it...
		sed -i -r -e 's,^((host|uri)[[:blank:]].*),# \1,g' $target
		# ... with the uri.
		egrep '^uri[[:blank:]]' $source >> $target
	elif egrep -q '^host[[:blank:]]' $source 2> /dev/null ; then
		# Comment out the packaged default host/uri and replace it...
		sed -i -r -e 's,^((host|uri)[[:blank:]].*),# \1,g' $target
		# ... with the "host" reformatted as a URI.
		scheme=ldap
		# check for 'ssl on', which means we want to use ldaps://
		if egrep -q '^ssl[[:blank:]]+on$' $source 2> /dev/null ; then
			scheme=ldaps
		fi
		egrep '^host[[:blank:]]' $source |\
		sed -r -e "s,^host[[:blank:]](.*),uri ${scheme}://\1/,g" >> $target
	fi
	# Base doesn't require any special logic.
	if egrep -q '^base[[:blank:]]' $source 2> /dev/null ; then
		# Comment out the packaged default base and replace it.
		sed -i -r -e 's,^(base[[:blank:]].*),# \1,g' $target
		egrep '^base[[:blank:]]' $source >> $target
	fi
	# Pull in these settings, if they're set, directly.
	egrep '^(binddn|bindpw|port|scope|ssl|pagesize)[[:blank:]]' $source 2> /dev/null >> $target
	egrep '^(tls_)' $source 2> /dev/null >> $target
	egrep '^(timelimit|bind_timelimit|idle_timelimit)[[:blank:]]' $source 2> /dev/null >> $target
fi
# If this is the first time we're being installed, and the system is already
# configured to use LDAP as a naming service, enable the daemon, but don't
# start it since we can never know if that's a safe thing to do.  If this
# is an upgrade, leave the user's runlevel selections alone.
if [ "$1" -eq "1" ]; then
	if egrep -q '^USELDAP=yes$' /etc/sysconfig/authconfig 2> /dev/null ; then
		/sbin/chkconfig nslcd on
	fi
fi
exit 0

%preun
if [ "$1" -eq "0" ]; then
	/sbin/service nslcd stop >/dev/null 2>&1
	/sbin/chkconfig --del nslcd
fi
exit 0

%postun
/sbin/ldconfig
if [ "$1" -ge "1" ]; then
	/etc/rc.d/init.d/nslcd condrestart >/dev/null 2>&1
fi
exit 0

%changelog
* Mon May 17 2010 Nalin Dahyabhai <nalin@redhat.com> 0.7.5-3
- switch to the upstream patch for #592965

* Fri May 14 2010 Nalin Dahyabhai <nalin@redhat.com> 0.7.5-2
- don't return an uninitialized buffer as the value for an optional attribute
  that isn't present in the directory server entry (#592965)

* Fri May 14 2010 Nalin Dahyabhai <nalin@redhat.com> 0.7.5-1
- update to 0.7.5

* Fri May 14 2010 Nalin Dahyabhai <nalin@redhat.com> 0.7.4-1
- update to 0.7.4 (#592385)
- stop trying to migrate retry timeout parameters from old ldap.conf files
- add an explicit requires: on nscd to make sure it's at least available
  on systems that are using nss-pam-ldapd; otherwise it's usually optional
  (#587306)

* Tue Mar 23 2010 Nalin Dahyabhai <nalin@redhat.com> 0.7.3-1
- update to 0.7.3

* Thu Feb 25 2010 Nalin Dahyabhai <nalin@redhat.com> 0.7.2-2
- bump release for post-review commit

* Thu Feb 25 2010 Nalin Dahyabhai <nalin@redhat.com> 0.7.2-1
- add comments about why we have a .so link at all, and not a -devel subpackage

* Wed Jan 13 2010 Nalin Dahyabhai <nalin@redhat.com>
- obsolete/provides nss-ldapd
- import configuration from nss-ldapd.conf, too

* Tue Jan 12 2010 Nalin Dahyabhai <nalin@redhat.com>
- rename to nss-pam-ldapd
- also check for import settings in /etc/nss_ldap.conf and /etc/pam_ldap.conf

* Thu Sep 24 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.11-2
- rebuild

* Wed Sep 16 2009 Nalin Dahyabhai <nalin@redhat.com> 
- apply Mitchell Berger's patch to clean up the init script, use %%{_initddir},
  and correct the %%post so that it only thinks about turning on nslcd when
  we're first being installed (#522947)
- tell status() where the pidfile is when the init script is called for that

* Tue Sep  8 2009 Nalin Dahyabhai <nalin@redhat.com>
- fix typo in a comment, capitalize the full name for "LDAP Client User" (more
  from #516049)

* Wed Sep  2 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.11-1
- update to 0.6.11

* Sat Jul 25 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.6.10-4
- Rebuilt for https://fedoraproject.org/wiki/Fedora_12_Mass_Rebuild

* Thu Jun 18 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.10-3
- update URL: and Source:

* Mon Jun 15 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.10-2
- add and own /var/run/nslcd
- convert hosts to uri during migration

* Thu Jun 11 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.10-1
- update to 0.6.10

* Fri Apr 17 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.8-1
- bump release number to 1 (part of #491767)
- fix which group we check for during %%pre (part of #491767)

* Tue Mar 24 2009 Nalin Dahyabhai <nalin@redhat.com>
- require chkconfig by package rather than path (Jussi Lehtola, part of #491767)

* Mon Mar 23 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.8-0.1
- update to 0.6.8

* Mon Mar 23 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.7-0.1
- start using a dedicated user

* Wed Mar 18 2009 Nalin Dahyabhai <nalin@redhat.com> 0.6.7-0.0
- initial package (#445965)
