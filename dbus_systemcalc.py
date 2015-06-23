#!/usr/bin/python -u
# -*- coding: utf-8 -*-

from dbus.mainloop.glib import DBusGMainLoop
import gobject
from gobject import idle_add
import dbus
import dbus.service
import inspect
import platform
import logging
import argparse
import sys
import os
import json

# Victron packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), './ext/velib_python'))
from vedbus import VeDbusService, VeDbusItemImport
from dbusmonitor import DbusMonitor
from settingsdevice import SettingsDevice
from logger import setup_logging

softwareVersion = '1.09'

class SystemCalc:
	def __init__(self):
		self.STATE_IDLE = 0
		self.STATE_CHARGING = 1
		self.STATE_DISCHARGING = 2

		self.BATSERVICE_DEFAULT = 'default'
		self.BATSERVICE_NOBATTERY = 'nobattery'

		# Why this dummy? Because DbusMonitor expects these values to be there, even though we don't
		# need them. So just add some dummy data. This can go away when DbusMonitor is more generic.
		dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
		self._dbusmonitor = DbusMonitor({
			'com.victronenergy.solarcharger': {
				'/Connected': dummy,
				'/Dc/V': dummy,
				'/Dc/I': dummy},
			'com.victronenergy.pvinverter': {
				'/Connected': dummy,
				'/Ac/L1/Power': dummy,
				'/Ac/L2/Power': dummy,
				'/Ac/L3/Power': dummy,
				'/Position': dummy},
			'com.victronenergy.battery': {
				'/Connected': dummy,
				'/ProductName': dummy,
				'/Mgmt/Connection': dummy,
				'/Dc/0/V': dummy,
				'/Dc/0/I': dummy,
				'/Dc/0/P': dummy,
				'/Soc': dummy,
				'/TimeToGo': dummy,
				'/ConsumedAmphours': dummy},
			'com.victronenergy.vebus' : {
				'/Ac/ActiveIn/ActiveInput': dummy,
				'/Ac/ActiveIn/L1/P': dummy,
				'/Ac/ActiveIn/L2/P': dummy,
				'/Ac/ActiveIn/L3/P': dummy,
				'/Ac/Out/L1/P': dummy,
				'/Ac/Out/L2/P': dummy,
				'/Ac/Out/L3/P': dummy,
				'/Connected': dummy,
				'/Hub4/AcPowerSetpoint': dummy,
				'/ProductName': dummy,
				'/Mgmt/Connection': dummy,
				'/State': dummy,
				'/Dc/V': dummy,
				'/Dc/I': dummy,
				'/Dc/P': dummy,
				'/Soc': dummy},
			'com.victronenergy.charger': {
				'/Dc/0/V': dummy,
				'/Dc/0/I': dummy},
			'com.victronenergy.grid' : {
				'/ProductId' : dummy,
				'/DeviceType' : dummy,
				'/Ac/L1/Power': dummy,
				'/Ac/L2/Power': dummy,
				'/Ac/L3/Power': dummy},
			'com.victronenergy.genset' : {
				'/ProductId' : dummy,
				'/DeviceType' : dummy,
				'/Ac/L1/Power': dummy,
				'/Ac/L2/Power': dummy,
				'/Ac/L3/Power': dummy},
			'com.victronenergy.settings' : {
				'/Settings/SystemSetup/AcInput1' : dummy,
				'/Settings/SystemSetup/AcInput2' : dummy}
		}, self._dbus_value_changed, self._device_added, self._device_removed)

		# Connect to localsettings
		self._settings = SettingsDevice(
			bus=dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus(),
			supportedSettings={
				'batteryservice': ['/Settings/SystemSetup/BatteryService', self.BATSERVICE_DEFAULT, 0, 0],
				'hasdcsystem': ['/Settings/SystemSetup/HasDcSystem', 0, 0, 1]},
			eventCallback=self._handlechangedsetting)

		# put ourselves on the dbus
		self._dbusservice = VeDbusService('com.victronenergy.system')
		self._dbusservice.add_mandatory_paths(
			processname=__file__,
			processversion=softwareVersion,
			connection='data from other dbus processes',
			deviceinstance=0,
			productid=None,
			productname=None,
			firmwareversion=None,
			hardwareversion=None,
			connected=1)

		self._dbusservice.add_path('/Serial', value=_get_ccgx_serial())

		self._dbusservice.add_path(
			'/AvailableBatteryServices', value=None, gettextcallback=self._gettext)
		self._dbusservice.add_path(
			'/AutoSelectedBatteryService', value=None, gettextcallback=self._gettext)

		self._summeditems = {
			'/Ac/Grid/L1/Power': {'gettext': '%.0F W'},
			'/Ac/Grid/L2/Power': {'gettext': '%.0F W'},
			'/Ac/Grid/L3/Power': {'gettext': '%.0F W'},
			'/Ac/Grid/Total/Power': {'gettext': '%.0F W'},
			'/Ac/Grid/NumberOfPhases': {'gettext': '%.0F W'},
			'/Ac/Grid/ProductId': {'gettext': '%s'},
			'/Ac/Grid/DeviceType': {'gettext': '%s'},
			'/Ac/Genset/L1/Power': {'gettext': '%.0F W'},
			'/Ac/Genset/L2/Power': {'gettext': '%.0F W'},
			'/Ac/Genset/L3/Power': {'gettext': '%.0F W'},
			'/Ac/Genset/Total/Power': {'gettext': '%.0F W'},
			'/Ac/Genset/NumberOfPhases': {'gettext': '%.0F W'},
			'/Ac/Genset/ProductId': {'gettext': '%s'},
			'/Ac/Genset/DeviceType': {'gettext': '%s'},
			'/Ac/Consumption/L1/Power': {'gettext': '%.0F W'},
			'/Ac/Consumption/L2/Power': {'gettext': '%.0F W'},
			'/Ac/Consumption/L3/Power': {'gettext': '%.0F W'},
			'/Ac/Consumption/Total/Power': {'gettext': '%.0F W'},
			'/Ac/Consumption/NumberOfPhases': {'gettext': '%.0F W'},
			'/Ac/PvOnOutput/L1/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnOutput/L2/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnOutput/L3/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnOutput/Total/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnOutput/NumberOfPhases': {'gettext': '%.0F W'},
			'/Ac/PvOnGrid/L1/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnGrid/L2/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnGrid/L3/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnGrid/Total/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnGrid/NumberOfPhases': {'gettext': '%.0F W'},
			'/Ac/PvOnGenset/L1/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnGenset/L2/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnGenset/L3/Power': {'gettext': '%.0F W'},
			'/Ac/PvOnGenset/NumberOfPhases': {'gettext': '%d'},
			'/Ac/PvOnGenset/Total/Power': {'gettext': '%.0F W'},
			'/Dc/Pv/Power': {'gettext': '%.0F W'},
			'/Dc/Pv/Current': {'gettext': '%.1F A'},
			'/Dc/Battery/Voltage': {'gettext': '%.2F V'},
			'/Dc/Battery/Current': {'gettext': '%.1F A'},
			'/Dc/Battery/Power': {'gettext': '%.0F W'},
			'/Dc/Battery/Soc': {'gettext': '%.0F %%'},
			'/Dc/Battery/State': {'gettext': '%s'},
			'/Dc/Battery/TimeToGo': {'gettext': '%.0F s'},
			'/Dc/Battery/ConsumedAmphours': {'gettext': '%.1F Ah'},
			'/Dc/Charger/Power': {'gettext': '%.0F %%'},
			'/Dc/Vebus/Current': {'gettext': '%.1F A'},
			'/Dc/Vebus/Power': {'gettext': '%.0F W'},
			'/Dc/System/Power': {'gettext': '%.0F W'},
			'/Hub': {'gettext': '%s'},
			'/Ac/ActiveIn/Source': {'gettext': '%s'}
			}

		for path in self._summeditems.keys():
			self._dbusservice.add_path(path, value=None, gettextcallback=self._gettext)

		self._batteryservice = None
		self._determinebatteryservice()

		if self._batteryservice is None:
			logger.info("Battery service initialized to None (setting == %s)" %
				self._settings['batteryservice'])

		self._changed = True
		self._handleservicechange()
		self._updatevalues()
		gobject.timeout_add(1000, self._handletimertick)

	def _handlechangedsetting(self, setting, oldvalue, newvalue):
		self._determinebatteryservice()
		self._changed = True

	def _determinebatteryservice(self):
		if self._settings['batteryservice'] == self.BATSERVICE_DEFAULT:
			newbatteryservice = self._autoselect_battery_service()
			self._dbusservice['/AutoSelectedBatteryService'] = (
				'No battery monitor found' if newbatteryservice is None else
				self._get_readable_service_name(newbatteryservice))

		elif self._settings['batteryservice'] == self.BATSERVICE_NOBATTERY:
			self._dbusservice['/AutoSelectedBatteryService'] = None
			newbatteryservice = None

		else:
			self._dbusservice['/AutoSelectedBatteryService'] = None

			s = self._settings['batteryservice'].split('/')
			assert len(s) == 2, "The battery setting (%s) is invalid!" % self._settings['batteryservice']
			serviceclass = s[0]
			instance = int(s[1])
			services = self._dbusmonitor.get_service_list(classfilter=serviceclass)
			if instance not in services.values():
				# Once chosen battery monitor does not exist. Don't auto change the setting (it might come
				# back). And also don't autoselect another.
				newbatteryservice = None
			else:
				# According to https://www.python.org/dev/peps/pep-3106/, dict.keys() and dict.values()
				# always have the same order.
				newbatteryservice = services.keys()[services.values().index(instance)]

		if newbatteryservice != self._batteryservice:
			logger.info("Battery service, setting == %s, changed from %s to %s" %
				(self._settings['batteryservice'], self._batteryservice, newbatteryservice))
			self._batteryservice = newbatteryservice

	def _autoselect_battery_service(self):
		# Default setting business logic:
		# first try to use a battery service (BMV or Lynx Shunt VE.Can). If there
		# is more than one battery service, just use a random one. If no battery service is
		# available, check if there are not Solar chargers and no normal chargers. If they are not
		# there, assume this is a hub-2, hub-3 or hub-4 system and use VE.Bus SOC.
		batteries = self._dbusmonitor.get_service_list('com.victronenergy.battery')
		self._remove_unconnected_services(batteries)

		if len(batteries) > 0:
			return sorted(batteries)[0]  # Pick a random battery service

		if len(self._dbusmonitor.get_service_list('com.victronenergy.solarcharger')) > 0:
			return None

		if len(self._dbusmonitor.get_service_list('com.victronenergy.charger')) > 0:
			return None

		vebusses = self._dbusmonitor.get_service_list('com.victronenergy.vebus')
		self._remove_unconnected_services(vebusses)

		if len(vebusses) > 0:
			return sorted(vebusses)[0]  # Pick a random vebus service

		return None

	def _handletimertick(self):
		# try catch, to make sure that we kill ourselves on an error. Without this try-catch, there would
		# be an error written to stdout, and then the timer would not be restarted, resulting in a dead-
		# lock waiting for manual intervention -> not good!
		try:
			if self._changed:
				self._updatevalues()
			self._changed = False
		except:
			import traceback
			traceback.print_exc()
			sys.exit(1)

		return True  # keep timer running

	def _updatevalues(self):
		# ==== PREPARATIONS ====
		# Determine values used in logic below
		vebusses = self._dbusmonitor.get_service_list('com.victronenergy.vebus')
		vebuspower = 0
		for vebus in vebusses:
			v = self._dbusmonitor.get_value(vebus, '/Dc/V')
			i = self._dbusmonitor.get_value(vebus, '/Dc/I')
			if v is not None and i is not None:
				vebuspower += v * i

		# ==== PVINVERTERS ====
		pvinverters = self._dbusmonitor.get_service_list('com.victronenergy.pvinverter')
		newvalues = {}
		phases = ['1', '2', '3']
		pos = {0: '/Ac/PvOnGrid/', 1: '/Ac/PvOnOutput/', 2: '/Ac/PvOnGenset/'}
		total = {0: None, 1: None, 2: None}
		for pvinverter in pvinverters:
			position = self._dbusmonitor.get_value(pvinverter, '/Position')

			for phase in phases:
				power = self._dbusmonitor.get_value(pvinverter, '/Ac/L' + phase + '/Power')
				if power is None:
					continue

				path = pos[position] + 'L' + str(int(phase)) + '/Power'
				if path not in newvalues:
					newvalues[path] = power
				else:
					newvalues[path] += power

				total[position] = power if total[position] is None else total[position] + power

			# Determine number of phases.
			if pos[position] + 'L3' + '/Power' in newvalues:
				newvalues[pos[position] + 'NumberOfPhases'] = 3
			elif pos[position] + 'L2' + '/Power' in newvalues:
				newvalues[pos[position] + 'NumberOfPhases'] = 2
			elif pos[position] + 'L1' + '/Power' in newvalues:
				newvalues[pos[position] + 'NumberOfPhases'] = 1
			# no need to set it to None, not adding the item to newvalues has the same effect

		# Add totals
		newvalues['/Ac/PvOnGrid/Total/Power'] = total[0]
		newvalues['/Ac/PvOnOutput/Total/Power'] = total[1]
		newvalues['/Ac/PvOnGenset/Total/Power'] = total[2]

		# ==== SOLARCHARGERS ====
		solarchargers = self._dbusmonitor.get_service_list('com.victronenergy.solarcharger')
		solarcharger_batteryvoltage = None
		for solarcharger in solarchargers:
			v = self._dbusmonitor.get_value(solarcharger, '/Dc/V')
			if v is None:
				continue
			i = self._dbusmonitor.get_value(solarcharger, '/Dc/I')
			if i is None:
				continue

			if '/Dc/Pv/Power' not in newvalues:
				newvalues['/Dc/Pv/Power'] = v * i
				newvalues['/Dc/Pv/Current'] = i
				solarcharger_batteryvoltage = v
			else:
				newvalues['/Dc/Pv/Power'] += v * i
				newvalues['/Dc/Pv/Current'] += i

		# ==== CHARGERS ====
		chargers = self._dbusmonitor.get_service_list('com.victronenergy.charger')
		charger_batteryvoltage = None
		for charger in chargers:
			# Assume the battery connected to output 0 is the main battery
			v = self._dbusmonitor.get_value(charger, '/Dc/0/V')
			if v is None:
				continue

			charger_batteryvoltage = v

			i = self._dbusmonitor.get_value(charger, '/Dc/0/I')
			if i is None:
				continue

			if '/Dc/Charger/Power' not in newvalues:
				newvalues['/Dc/Charger/Power'] = v * i
			else:
				newvalues['/Dc/Charger/Power'] += v * i

		# ==== BATTERY ====
		if self._batteryservice is not None:
			batteryservicetype = self._batteryservice.split('.')[2]  # either 'battery' or 'vebus'
			newvalues['/Dc/Battery/Soc'] = self._dbusmonitor.get_value(self._batteryservice,'/Soc')
			newvalues['/Dc/Battery/TimeToGo'] = self._dbusmonitor.get_value(self._batteryservice,'/TimeToGo')
			newvalues['/Dc/Battery/ConsumedAmphours'] = self._dbusmonitor.get_value(self._batteryservice,'/ConsumedAmphours')

			if batteryservicetype == 'battery':
				newvalues['/Dc/Battery/Voltage'] = self._dbusmonitor.get_value(self._batteryservice, '/Dc/0/V')
				newvalues['/Dc/Battery/Current'] = self._dbusmonitor.get_value(self._batteryservice, '/Dc/0/I')
				newvalues['/Dc/Battery/Power'] = self._dbusmonitor.get_value(self._batteryservice, '/Dc/0/P')

			elif batteryservicetype == 'vebus':
				newvalues['/Dc/Battery/Voltage'] = self._dbusmonitor.get_value(self._batteryservice, '/Dc/V')
				newvalues['/Dc/Battery/Current'] = self._dbusmonitor.get_value(self._batteryservice, '/Dc/I')
				if newvalues['/Dc/Battery/Voltage'] is not None and newvalues['/Dc/Battery/Current'] is not None:
					newvalues['/Dc/Battery/Power'] = (
						newvalues['/Dc/Battery/Voltage'] * newvalues['/Dc/Battery/Current'])

			p = newvalues.get('/Dc/Battery/Power', None)
			if p is not None:
				if p > 30:
					newvalues['/Dc/Battery/State'] = self.STATE_CHARGING
				elif p < -30:
					newvalues['/Dc/Battery/State'] = self.STATE_DISCHARGING
				else:
					newvalues['/Dc/Battery/State'] = self.STATE_IDLE

		else:
			batteryservicetype = None
			if solarcharger_batteryvoltage is not None:
				newvalues['/Dc/Battery/Voltage'] = solarcharger_batteryvoltage
			elif charger_batteryvoltage is not None:
				newvalues['/Dc/Battery/Voltage'] = charger_batteryvoltage
			else:
				# CCGX-connected system consists of only a Multi, but it is not user-selected, nor
				# auto-selected as the battery-monitor, probably because there are other loads or chargers.
				# In that case, at least use its reported battery voltage.
				vebusses = self._dbusmonitor.get_service_list('com.victronenergy.vebus')
				for vebus in vebusses:
					v = self._dbusmonitor.get_value(vebus, '/Dc/V')
					if v is not None:
						newvalues['/Dc/Battery/Voltage'] = v

			if self._settings['hasdcsystem'] == 0 and '/Dc/Battery/Voltage' in newvalues:
				# No unmonitored DC loads or chargers, and also no battery monitor: derive battery watts
				# and amps from vebus, solarchargers and chargers.
				assert '/Dc/Battery/Power' not in newvalues
				assert '/Dc/Battery/Current' not in newvalues
				p = newvalues.get('/Dc/Pv/Power', 0) + newvalues.get('/Dc/Charger/Power', 0) + vebuspower
				newvalues['/Dc/Battery/Current'] = p / newvalues['/Dc/Battery/Voltage']
				newvalues['/Dc/Battery/Power'] = p

		# ==== SYSTEM ====
		if self._settings['hasdcsystem'] == 1 and batteryservicetype == 'battery':
			# Calculate power being generated/consumed by not measured devices in the network.
			# /Dc/System: positive: consuming power
			# VE.Bus: Positive: current flowing from the Multi to the dc system or battery
			# Solarcharger & other chargers: positive: charging
			# battery: Positive: charging battery.
			# battery = solarcharger + charger + ve.bus - system

			newvalues['/Dc/System/Power'] = (newvalues.get('/Dc/Pv/Power', 0) +
				newvalues.get('/Dc/Charger/Power', 0) +	vebuspower - newvalues['/Dc/Battery/Power'])

		# ==== Vebus ====
		multis = self._dbusmonitor.get_service_list('com.victronenergy.vebus')
		multi_path = None
		if len(multis) > 0:
			# Assume there's only 1 multi service present on the D-Bus
			multi_path = multis.keys()[0]
			dc_current = self._dbusmonitor.get_value(multi_path, '/Dc/I')
			newvalues['/Dc/Vebus/Current'] = dc_current
			dc_power = self._dbusmonitor.get_value(multi_path, '/Dc/P')
			# Just in case /Dc/P is not available
			if dc_power == None and dc_current is not None:
				dc_voltage = self._dbusmonitor.get_value(multi_path, '/Dc/V')
				if dc_voltage is not None:
					dc_power = dc_voltage * dc_current
			# Note that there is also vebuspower, which is the total DC power summed over all multis.
			# However, this value cannot be combined with /Dc/Multi/Current, because it does not make sense
			# to add the Dc currents of all multis if they do not share the same DC voltage.
			newvalues['/Dc/Vebus/Power'] = dc_power

		# ===== AC IN SOURCE =====
		ac_in_source = None
		active_input = self._dbusmonitor.get_value(multi_path, '/Ac/ActiveIn/ActiveInput')
		if active_input is not None:
			settings_path = '/Settings/SystemSetup/AcInput%s' % (active_input + 1)
			ac_in_source = self._dbusmonitor.get_value('com.victronenergy.settings', settings_path)
		newvalues['/Ac/ActiveIn/Source'] = ac_in_source

		# ===== HUB MODE =====
		# The code below should be executed after PV inverter data has been updated, because we need the
		# PV inverter total power to update the consumption.
		hub = None
		if self._dbusmonitor.get_value(multi_path, '/Hub4/AcPowerSetpoint') is not None:
			hub = 4
		elif newvalues.get('/Dc/Pv/Power', None) is not None:
			hub = 1
		elif newvalues.get('/Ac/PvOnOutput/Total/Power', None) is not None:
			hub = 2
		elif newvalues.get('/Ac/PvOnGrid/Total/Power', None) is not None or \
			newvalues.get('/Ac/PvOnGenset/Total/Power', None) is not None:
			hub = 3
		newvalues['/Hub'] = hub

		# ===== GRID METERS & CONSUMPTION ====
		consumption = { "L1" : None, "L2" : None, "L3" : None }
		for device_type in ['Grid', 'Genset']:
			servicename = 'com.victronenergy.%s' % device_type.lower()
			energy_meters = self._dbusmonitor.get_service_list(servicename)
			em_service = None
			if len(energy_meters) > 0:
				# Take the first meter, we assume there's only one present. We also assume that the device is
				# currently online.
				em_service = energy_meters.keys()[0]
			uses_active_input = False
			if multi_path is not None:
				# If a grid meter is present we use values from it. If not, we look at the multi. If it has
				# AcIn1 or AcIn2 connected to the grid, we use those values.
				# com.victronenergy.grid.??? indicates presence of an energy meter used as grid meter.
				# com.victronenergy.vebus.???/Ac/ActiveIn/ActiveInput: decides which whether we look at AcIn1
				# or AcIn2 as possible grid connection.
				if ac_in_source is not None:
					uses_active_input = ac_in_source > 0 and (ac_in_source == 2) == (device_type == 'Genset')
			for phase in consumption:
				p = None
				pvpower = newvalues.get('/Ac/PvOn%s/%s/Power' % (device_type, phase))
				if em_service is not None:
					p = self._dbusmonitor.get_value(em_service, '/Ac/%s/Power' % phase)
					# Compute consumption between energy meter and multi (meter power - multi AC in) and
					# add an optional PV inverter on input to the mix.
					c = consumption[phase]
					if uses_active_input:
						ac_in = self._dbusmonitor.get_value(multi_path, '/Ac/ActiveIn/%s/P' % phase)
						if ac_in is not None:
							c = _safeadd(c, -ac_in)
					# If there's any power coming from a PV inverter in the inactive AC in (which is unlikely),
					# it will still be used, because there may also be a load in the same ACIn consuming
					# power, or the power could be fed back to the net.
					c = _safeadd(c, p, pvpower)
					consumption[phase] = None if c is None else max(0, c)
				else:
					if uses_active_input:
						p = self._dbusmonitor.get_value(multi_path, '/Ac/ActiveIn/%s/P' % phase)
					# No relevant energy meter present. Assume there is no load between the grid and the multi.
					# There may be a PV inverter present though (Hub-3 setup).
					if pvpower != None:
						p = _safeadd(p, -pvpower)
				newvalues['/Ac/%s/%s/Power' % (device_type, phase)] = p
			self._compute_phase_totals('/Ac/%s' % device_type, newvalues)
			if em_service is not None:
				newvalues['/Ac/%s/ProductId' % device_type] = self._dbusmonitor.get_value(em_service, '/ProductId')
				newvalues['/Ac/%s/DeviceType' % device_type] = self._dbusmonitor.get_value(em_service, '/DeviceType')
		for phase in consumption:
			c = consumption[phase]
			pvpower = newvalues.get('/Ac/PvOnOutput/%s/Power' % phase)
			c = _safeadd(c, pvpower)
			if multi_path is not None:
				ac_out = self._dbusmonitor.get_value(multi_path, '/Ac/Out/%s/P' % phase)
				c = _safeadd(c, ac_out)
			newvalues['/Ac/Consumption/%s/Power' % phase] = None if c is None else max(0, c)
		self._compute_phase_totals('/Ac/Consumption', newvalues)
		# TODO EV Add Multi DeviceType & ProductID. Unfortunately, the com.victronenergy.vebus.??? tree does
		# not contain a /ProductId entry.

		# ==== UPDATE DBUS ITEMS ====
		for path in self._summeditems.keys():
			# Why the None? Because we want to invalidate things we don't have anymore.
			self._dbusservice[path] = newvalues.get(path, None)

	def _handleservicechange(self):
		# Update the available battery monitor services, used to populate the dropdown in the settings.
		# Below code makes a dictionary. The key is [dbuserviceclass]/[deviceinstance]. For example
		# "battery/245". The value is the name to show to the user in the dropdown. The full dbus-
		# servicename, ie 'com.victronenergy.vebus.ttyO1' is not used, since the last part of that is not
		# fixed. dbus-serviceclass name and the device instance are already fixed, so best to use those.

		services = self._dbusmonitor.get_service_list('com.victronenergy.vebus')
		services.update(self._dbusmonitor.get_service_list('com.victronenergy.battery'))
		self._remove_unconnected_services(services)

		ul = {self.BATSERVICE_DEFAULT: 'Automatic', self.BATSERVICE_NOBATTERY: 'No battery monitor'}
		for servicename, instance in services.items():
			key = "%s/%s" % ('.'.join(servicename.split('.')[0:3]), instance)
			ul[key] = self._get_readable_service_name(servicename)

		self._dbusservice['/AvailableBatteryServices'] = json.dumps(ul)

		self._determinebatteryservice()

		self._changed = True

	def _get_readable_service_name(self, servicename):
		return (self._dbusmonitor.get_value(servicename, '/ProductName') + ' on ' +
						self._dbusmonitor.get_value(servicename, '/Mgmt/Connection'))

	def _remove_unconnected_services(self, services):
		# Workaround: because com.victronenergy.vebus is available even when there is no vebus product
		# connected. Remove any that is not connected. For this, we use /State since mandatory path
		# /Connected is not implemented in mk2dbus.
		for servicename in services.keys():
			if ((servicename.split('.')[2] == 'vebus' and self._dbusmonitor.get_value(servicename, '/State') is None)
				or self._dbusmonitor.get_value(servicename, '/Connected') != 1
				or self._dbusmonitor.get_value(servicename, '/ProductName') is None
				or self._dbusmonitor.get_value(servicename, '/Mgmt/Connection') is None):
				del services[servicename]

	def _dbus_value_changed(self, dbusServiceName, dbusPath, dict, changes, deviceInstance):
		self._changed = True

		# Workaround because com.victronenergy.vebus is available even when there is no vebus product
		# connected.
		if (dbusPath in ['/Connected', '/ProductName', '/Mgmt/Connection'] or
			(dbusPath == '/State' and dbusServiceName.split('.')[0:3] == ['com', 'victronenergy', 'vebus'])):
			self._handleservicechange()

	def _device_added(self, service, instance):
		self._handleservicechange()

	def _device_removed(self, service, instance):
		self._handleservicechange()

	def _gettext(self, path, value):
		if path in ['/AvailableBatteryServices', '/AutoSelectedBatteryService']:
			return value
		elif path == '/Dc/Battery/State':
			state = {self.STATE_IDLE: 'Idle', self.STATE_CHARGING: 'Charging',
				self.STATE_DISCHARGING: 'Discharging'}
			return state[value]
		return (self._summeditems[path]['gettext'] % (value))

	def _compute_phase_totals(self, path, newvalues):
		total_power = None
		number_of_phases = 0
		for phase in ['L1', 'L2', 'L3']:
			p = newvalues['%s/%s/Power' % (path, phase)]
			total_power = _safeadd(total_power, p)
			if p is not None:
				number_of_phases += 1
		newvalues[path + '/Total/Power'] = total_power
		newvalues[path + '/NumberOfPhases'] = number_of_phases if number_of_phases > 0 else None

def _safeadd(*values):
	'''Adds all parameters passed to this function. Parameters which are None are ignored. If all parameters
	are None, the function will return None as well.'''
	r = None
	for v in values:
		if v is not None:
			if r is None:
				r = v
			else:
				r += v
	return r

def _get_ccgx_serial():
	'''Returns the MAC address ascociated with eth0. Example: 087ba61221a0.
	This value is used as ID for the VRM portal, so it may be considered as the serial number of the CCGX.'''
	# Assume we are on linux
	import fcntl, socket, struct

	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	info = fcntl.ioctl(s.fileno(), 0x8927,  struct.pack('256s', 'eth0'))
	return ''.join('%02x' % ord(x) for x in info[18:24])

if __name__ == "__main__":
	# Argument parsing
	parser = argparse.ArgumentParser(
		description='Converts readings from AC-Sensors connected to a VE.Bus device in a pvinverter ' +
					'D-Bus service.'
	)

	parser.add_argument("-d", "--debug", help="set logging level to debug",
					action="store_true")

	args = parser.parse_args()

	print("-------- dbus_systemcalc, v" + softwareVersion + " is starting up --------")
	logger = setup_logging(args.debug)

	# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
	DBusGMainLoop(set_as_default=True)

	systemcalc = SystemCalc()

	# Start and run the mainloop
	logger.info("Starting mainloop, responding only on events")
	mainloop = gobject.MainLoop()
	mainloop.run()
